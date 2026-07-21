"""Wearable-badge gateway ingest + fleet logic (wearable-badge capability).

Badges detect each other over ESP-NOW and gateways relay what they heard
to `POST /api/gateway/ingest/`. This module owns the server side of that
wire protocol:

- `process_gateway_batch` validates and dedupes a gateway batch, then
  TRANSLATES badge observations into the existing phone-BLE substrate:
  each observing badge's active assignment resolves to a (session,
  player), the seen badge resolves to the seen player's ProximityIdentity
  token, and a ProximityReport tagged source=BADGE is written. The same
  `run_tick` derivation + dementors economy the phone path uses then
  consumes it — the energy economy is transport-agnostic by construction.
- Telemetry (battery, IMU activity class, gesture events, dead-reckoning
  payloads) lands in BadgeTelemetry and refreshes the fleet registry.
- The ingest response carries per-badge authoritative display state
  (energy/role → ring-light pattern) for the gateway to re-broadcast.

Only observations are accepted. Any outcome-shaped keys a badge or
gateway asserts (role, energy, ...) are simply never read — the server
computes all energy changes and role flips itself.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from game.models import (
    PROXIMITY_SOURCE_BADGE,
    BadgeAssignment,
    BadgeDevice,
    BadgeObservationSeen,
    BadgeTelemetry,
    DementorState,
    ProximityIdentity,
    ProximityReport,
)
from game.proximity import RSSI_MAX, RSSI_MIN

# Wire-protocol version spoken by /api/gateway/ingest/. Bump on breaking
# changes; firmware records its own copy in firmware/common/protocol.h.
GATEWAY_PROTOCOL_VERSION = 1

# Firmware version the backend currently expects; badges reporting an
# older (different) version are flagged `firmware_stale` in inventory.
CURRENT_FIRMWARE_VERSION = '0.1.0'

# Fleet health thresholds surfaced by the staff inventory view.
LOW_BATTERY_PCT = 20
STALE_DEVICE_SECONDS = 600

# Batch size caps: one gateway POST beyond these is truncated (entries
# past the cap are counted as discarded), mirroring the phone-path cap.
MAX_OBSERVATIONS_PER_INGEST = 500
MAX_TELEMETRY_PER_INGEST = 200

# Dedup markers older than this are pruned; rolling beacon counters take
# far longer than 15 minutes to repeat a (badge, seen, counter) triple.
DEDUP_RETENTION_SECONDS = 900

VALID_ACTIVITIES = {'RUNNING', 'STANDING', 'STILL'}
VALID_GESTURES = {'CAST', 'DRAIN'}

# Ring-light display patterns pushed back to badges. The badge renders
# whatever the server last said; on downlink loss the firmware holds
# last-known state and overlays its own stale/disconnected pattern.
RING_PATTERN_ENERGY_FILL = 'ENERGY_FILL'
RING_PATTERN_OUT = 'OUT'
RING_PATTERN_IDLE = 'IDLE'
RING_COLOR_WIZARD = 'WARM'
RING_COLOR_DEMENTOR = 'COLD'


def battery_low(badge):
    return badge.battery_pct is not None and badge.battery_pct < LOW_BATTERY_PCT


def device_stale(last_seen_at, now=None):
    """A device is stale when it has never reported or reported too long ago."""
    now = now or timezone.now()
    if last_seen_at is None:
        return True
    return (now - last_seen_at).total_seconds() > STALE_DEVICE_SECONDS


def firmware_stale(badge):
    """Reported firmware differs from what the backend expects.

    An empty firmware_version (never reported) is not flagged — `stale`
    (last-seen) already covers silent devices.
    """
    return bool(badge.firmware_version) and badge.firmware_version != CURRENT_FIRMWARE_VERSION


def _clean_observation(entry):
    """Validated `(badge_id, seen_badge_id, rssi, counter, ts)` or None.

    Outcome-shaped keys (role/energy/...) are never read: only the
    observation fields exist as far as the server is concerned.
    """
    if not isinstance(entry, dict):
        return None
    badge_id = entry.get('badge_id')
    seen_badge_id = entry.get('seen_badge_id')
    rssi = entry.get('rssi')
    counter = entry.get('counter')
    if not isinstance(badge_id, str) or not badge_id:
        return None
    if not isinstance(seen_badge_id, str) or not seen_badge_id:
        return None
    if badge_id == seen_badge_id:
        return None
    if isinstance(rssi, bool) or not isinstance(rssi, (int, float)):
        return None
    rssi = int(rssi)
    if not (RSSI_MIN <= rssi <= RSSI_MAX):
        return None
    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        return None
    return badge_id, seen_badge_id, rssi, counter, _parse_ts(entry.get('ts'))


def _parse_ts(value):
    """Device-claimed timestamp → aware datetime or None. Untrusted:
    malformed values are dropped, never allowed to break the batch."""
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _clean_telemetry(entry):
    """Validated telemetry dict (badge_id + optional health fields) or None."""
    if not isinstance(entry, dict):
        return None
    badge_id = entry.get('badge_id')
    if not isinstance(badge_id, str) or not badge_id:
        return None
    cleaned = {'badge_id': badge_id}
    battery = entry.get('battery_pct')
    if isinstance(battery, (int, float)) and not isinstance(battery, bool):
        battery = int(battery)
        if 0 <= battery <= 100:
            cleaned['battery_pct'] = battery
    activity = entry.get('activity')
    if isinstance(activity, str) and activity.upper() in VALID_ACTIVITIES:
        cleaned['activity'] = activity.upper()
    gesture = entry.get('gesture')
    if isinstance(gesture, str) and gesture.upper() in VALID_GESTURES:
        cleaned['gesture'] = gesture.upper()
    imu = entry.get('imu')
    if isinstance(imu, dict):
        cleaned['imu'] = imu
    firmware = entry.get('firmware_version')
    if isinstance(firmware, str) and firmware:
        cleaned['firmware_version'] = firmware[:32]
    cleaned['ts'] = _parse_ts(entry.get('ts'))
    return cleaned


def _identity_for(session, player):
    """Current ProximityIdentity for (session, player), issued lazily.

    Badges join the exact same identity space phones use, so a player
    running badge + phone simultaneously fuses into one pair stream.
    """
    identity = ProximityIdentity.current_for(session, player)
    if identity is None:
        identity = ProximityIdentity.issue(session, player)
    return identity


def _resolve_badges(badge_ids):
    """badge_id → (BadgeDevice, active BadgeAssignment or None)."""
    devices = BadgeDevice.objects.filter(badge_id__in=badge_ids)
    by_id = {device.badge_id: (device, None) for device in devices}
    assignments = (
        BadgeAssignment.objects
        .filter(badge__badge_id__in=badge_ids, released_at__isnull=True)
        .select_related('badge', 'session__game', 'player__user', 'team')
    )
    for assignment in assignments:
        by_id[assignment.badge.badge_id] = (assignment.badge, assignment)
    return by_id


def _mark_seen(marker_rows, now):
    """Insert dedup markers; returns the set of rows that were new.

    Uses per-row get_or_create semantics under a race-safe insert so two
    gateways relaying the same observation concurrently cannot both win.
    """
    fresh = set()
    for badge, seen_badge, counter in marker_rows:
        try:
            with transaction.atomic():
                BadgeObservationSeen.objects.create(
                    badge=badge, seen_badge=seen_badge, counter=counter,
                )
            fresh.add((badge.pk, seen_badge.pk, counter))
        except IntegrityError:
            pass
    BadgeObservationSeen.objects.filter(
        received_at__lt=now - timedelta(seconds=DEDUP_RETENTION_SECONDS),
    ).delete()
    return fresh


def ring_state(assignment, state):
    """Server-authored ring display for one badge (energy/role → light).

    A pure function of server state: the badge renders it verbatim. IDLE
    when the session's dementors mode is off or the badge has no
    per-player state to show.
    """
    if state is None:
        return {'pattern': RING_PATTERN_IDLE, 'fill_pct': 0, 'color': None}
    if not state.alive:
        return {'pattern': RING_PATTERN_OUT, 'fill_pct': 0, 'color': RING_COLOR_DEMENTOR}
    starting = assignment.session.effective('dementor_starting_energy') or 1.0
    fill = int(round(100.0 * state.energy / starting))
    return {
        'pattern': RING_PATTERN_ENERGY_FILL,
        'fill_pct': max(0, min(100, fill)),
        'color': (
            RING_COLOR_WIZARD
            if state.role == DementorState.WIZARD
            else RING_COLOR_DEMENTOR
        ),
    }


def badge_states(sessions, now=None):
    """Per-badge authoritative state for the gateway downlink.

    Covers every badge actively assigned in `sessions`. Deliberately
    identity-free: the payload is re-broadcast on the open mesh, so it
    carries only the opaque badge id and display state.
    """
    states = []
    assignments = (
        BadgeAssignment.objects
        .filter(session__in=list(sessions), released_at__isnull=True)
        .select_related('badge', 'session__game', 'player')
        .order_by('badge__badge_id')
    )
    for assignment in assignments:
        dementor_state = None
        if assignment.player_id and assignment.session.effective('dementors_enabled'):
            dementor_state = DementorState.objects.filter(
                session=assignment.session, player_id=assignment.player_id,
            ).first()
        entry = {
            'badge_id': assignment.badge.badge_id,
            'role': dementor_state.role if dementor_state else None,
            'energy': round(dementor_state.energy, 2) if dementor_state else None,
            'alive': dementor_state.alive if dementor_state else None,
            'ring': ring_state(assignment, dementor_state),
        }
        states.append(entry)
    return states


def process_gateway_batch(gateway, payload, now=None):
    """Ingest one authenticated gateway batch; returns the response body.

    Steps: validate + cap the batches, dedupe observations by
    (badge, seen badge, counter), translate what remains into
    ProximityReports (source=BADGE) against the phone-BLE substrate,
    persist telemetry, run the server tick per touched session, and
    assemble the per-badge display-state downlink.
    """
    from game.dementors import run_tick

    now = now or timezone.now()

    raw_observations = payload.get('observations') or []
    raw_telemetry = payload.get('telemetry') or []
    if not isinstance(raw_observations, list):
        raw_observations = []
    if not isinstance(raw_telemetry, list):
        raw_telemetry = []

    discarded_obs = 0
    duplicates = 0
    observations = []
    for index, entry in enumerate(raw_observations):
        if index >= MAX_OBSERVATIONS_PER_INGEST:
            discarded_obs += 1
            continue
        cleaned = _clean_observation(entry)
        if cleaned is None:
            discarded_obs += 1
            continue
        observations.append(cleaned)

    discarded_tel = 0
    telemetry = []
    for index, entry in enumerate(raw_telemetry):
        if index >= MAX_TELEMETRY_PER_INGEST:
            discarded_tel += 1
            continue
        cleaned = _clean_telemetry(entry)
        if cleaned is None:
            discarded_tel += 1
            continue
        telemetry.append(cleaned)

    all_ids = {obs[0] for obs in observations}
    all_ids |= {obs[1] for obs in observations}
    all_ids |= {entry['badge_id'] for entry in telemetry}
    badge_map = _resolve_badges(all_ids)

    # --- Dedup + resolve observations --------------------------------------
    marker_rows = []
    resolvable = []
    for badge_id, seen_badge_id, rssi, counter, ts in observations:
        observer = badge_map.get(badge_id)
        seen = badge_map.get(seen_badge_id)
        if observer is None or seen is None:
            discarded_obs += 1  # unknown badge id(s)
            continue
        marker_rows.append((observer[0], seen[0], counter))
        resolvable.append((observer, seen, rssi, counter, ts))

    fresh = _mark_seen(marker_rows, now)

    # observer badge_id → list of {'token', 'rssi'} in identity space.
    per_observer = {}
    observer_meta = {}
    accepted_obs = 0
    seen_on_air = set()
    for (observer_device, observer_assignment), (seen_device, seen_assignment), \
            rssi, counter, ts in resolvable:
        seen_on_air.add(observer_device.pk)
        seen_on_air.add(seen_device.pk)
        marker_key = (observer_device.pk, seen_device.pk, counter)
        if marker_key not in fresh:
            duplicates += 1
            continue
        # Consume the marker so an in-batch repeat also counts as a dupe.
        fresh.discard(marker_key)
        if observer_assignment is None or observer_assignment.player_id is None:
            discarded_obs += 1  # unassigned or team-only badge can't report
            continue
        if (
            seen_assignment is None
            or seen_assignment.player_id is None
            or seen_assignment.session_id != observer_assignment.session_id
        ):
            discarded_obs += 1  # unresolvable or cross-session sighting
            continue
        session = observer_assignment.session
        seen_identity = _identity_for(session, seen_assignment.player)
        per_observer.setdefault(observer_device.badge_id, []).append(
            {'token': seen_identity.token, 'rssi': rssi},
        )
        observer_meta[observer_device.badge_id] = (observer_assignment, ts)
        accepted_obs += 1

    sessions_touched = {}
    for badge_id, entries in per_observer.items():
        assignment, ts = observer_meta[badge_id]
        session = assignment.session
        reporter_identity = _identity_for(session, assignment.player)
        ProximityReport.objects.create(
            session=session,
            reporter=reporter_identity,
            player=assignment.player,
            observations=entries,
            source=PROXIMITY_SOURCE_BADGE,
            reported_at=ts or None,
        )
        sessions_touched[session.pk] = session

    # --- Telemetry ----------------------------------------------------------
    accepted_tel = 0
    for entry in telemetry:
        resolved = badge_map.get(entry['badge_id'])
        if resolved is None:
            discarded_tel += 1
            continue
        device, assignment = resolved
        BadgeTelemetry.objects.create(
            badge=device,
            session=assignment.session if assignment else None,
            battery_pct=entry.get('battery_pct'),
            activity=entry.get('activity'),
            gesture=entry.get('gesture'),
            imu=entry.get('imu') or {},
            reported_at=entry.get('ts') or None,
        )
        update_fields = ['last_seen_at']
        device.last_seen_at = now
        if 'battery_pct' in entry:
            device.battery_pct = entry['battery_pct']
            update_fields.append('battery_pct')
        if entry.get('firmware_version'):
            device.firmware_version = entry['firmware_version']
            update_fields.append('firmware_version')
        device.save(update_fields=update_fields)
        seen_on_air.discard(device.pk)
        accepted_tel += 1

    # Any badge heard on the mesh (observer or seen) is alive: refresh
    # last-seen even without a telemetry entry this batch.
    if seen_on_air:
        BadgeDevice.objects.filter(pk__in=seen_on_air).update(last_seen_at=now)

    # --- Server tick + downlink --------------------------------------------
    events_derived = 0
    for session in sessions_touched.values():
        events_derived += len(run_tick(session))

    downlink_sessions = sessions_touched.values()
    if not sessions_touched:
        # Nothing ingested this round (e.g. a heartbeat poll): still hand
        # the gateway every active assignment's state to re-broadcast.
        downlink_sessions = {
            assignment.session_id: assignment.session
            for assignment in BadgeAssignment.objects.filter(
                released_at__isnull=True,
            ).select_related('session__game')
        }.values()

    return {
        'protocol_version': GATEWAY_PROTOCOL_VERSION,
        'accepted': {'observations': accepted_obs, 'telemetry': accepted_tel},
        'discarded': {
            'observations': discarded_obs,
            'duplicates': duplicates,
            'telemetry': discarded_tel,
        },
        'events_derived': events_derived,
        'badge_states': badge_states(downlink_sessions, now=now),
    }
