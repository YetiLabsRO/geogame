"""Server-side BLE proximity derivation (ble-proximity capability).

Phones are untrusted sensors: they advertise an ephemeral token and
report the tokens + RSSI they hear (ProximityReport). This module owns
the authoritative interpretation of those reports:

- `rssi_to_bucket` maps RSSI to a coarse ordinal bucket (never metres),
  with hysteresis so a signal hovering at a boundary does not oscillate.
- `derive_proximity` runs one derivation pass over the freshness window,
  fusing both directions of each pair into at most one ProximityEvent
  with a corroboration-boosted confidence, after plausibility filters
  (expired IDs, impossible crowds). Stale/absent reports simply produce
  no events — absence is never penalized.

Everything is deterministic and takes an explicit `now` for testability;
there is no celery/cron dependency (the tick runs on report ingestion).
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from game.models import ProximityEvent, ProximityIdentity, ProximityReport
from organize.models import (
    PROXIMITY_BUCKET_FAR,
    PROXIMITY_BUCKET_NEAR,
    PROXIMITY_BUCKET_VERY_CLOSE,
)

# Ordinal order, closest first. Used to compare buckets against the
# configured drain-range bucket ("within range" ⇔ order ≤ range order).
BUCKET_ORDER = {
    PROXIMITY_BUCKET_VERY_CLOSE: 0,
    PROXIMITY_BUCKET_NEAR: 1,
    PROXIMITY_BUCKET_FAR: 2,
}

# Sanity range for a BLE RSSI reading in dBm.
RSSI_MIN = -127
RSSI_MAX = 20

# Size cap for one report batch: entries beyond this are discarded at
# ingestion so one device cannot flood the session (spec: size-cap).
MAX_OBSERVATIONS_PER_REPORT = 150

# Impossible-crowd plausibility filter: a single phone claiming more
# simultaneous contacts than this is excluded from derivation.
MAX_PLAUSIBLE_CONTACTS = 80

# Report-rate plausibility: allow small bursts, but more than this many
# reports inside one report interval is "a rate far above the cadence".
REPORT_RATE_BURST = 3

# Confidence assigned to a derived pair: one-directional sighting vs
# both phones corroborating each other.
CONFIDENCE_ONE_WAY = 0.5
CONFIDENCE_CORROBORATED = 0.9


def rssi_to_bucket(rssi, *, very_close_dbm, near_dbm, hysteresis_db=0, previous=None):
    """Map an RSSI reading to a coarse ordinal bucket, with hysteresis.

    Thresholds are "at or above": `rssi >= very_close_dbm` is VERY_CLOSE,
    `rssi >= near_dbm` is NEAR, anything weaker is FAR. When `previous`
    (the pair's last derived bucket) is given, every boundary shifts by
    `hysteresis_db` in favor of staying in the previous bucket, so a
    signal hovering at a boundary does not rapidly oscillate.
    """
    vc, nr = very_close_dbm, near_dbm
    if previous == PROXIMITY_BUCKET_VERY_CLOSE:
        vc -= hysteresis_db
        nr -= hysteresis_db
    elif previous == PROXIMITY_BUCKET_NEAR:
        vc += hysteresis_db
        nr -= hysteresis_db
    elif previous == PROXIMITY_BUCKET_FAR:
        vc += hysteresis_db
        nr += hysteresis_db
    if rssi >= vc:
        return PROXIMITY_BUCKET_VERY_CLOSE
    if rssi >= nr:
        return PROXIMITY_BUCKET_NEAR
    return PROXIMITY_BUCKET_FAR


def clean_observations(raw):
    """Validate + size-cap a raw observation batch from one phone.

    Keeps well-formed `{'token': str, 'rssi': int}` entries with a sane
    RSSI, truncating at MAX_OBSERVATIONS_PER_REPORT. Returns
    `(kept, discarded_count)`; malformed entries count as discarded.
    """
    if not isinstance(raw, list):
        return [], 0
    kept, discarded = [], 0
    for entry in raw:
        if len(kept) >= MAX_OBSERVATIONS_PER_REPORT:
            discarded += 1
            continue
        if not isinstance(entry, dict):
            discarded += 1
            continue
        token = entry.get('token')
        rssi = entry.get('rssi')
        if not isinstance(token, str) or not token:
            discarded += 1
            continue
        if isinstance(rssi, bool) or not isinstance(rssi, (int, float)):
            discarded += 1
            continue
        rssi = int(rssi)
        if not (RSSI_MIN <= rssi <= RSSI_MAX):
            discarded += 1
            continue
        kept.append({'token': token, 'rssi': rssi})
    return kept, discarded


def resolvable_identities(session, now=None):
    """token → ProximityIdentity map for tokens valid this pass.

    Active identities always resolve. A retired (rotated) token stays
    resolvable while its retirement is inside the freshness window, then
    goes dark — a replayed old token cannot be farmed indefinitely.
    """
    now = now or timezone.now()
    window = timedelta(seconds=session.effective('ble_freshness_window_seconds'))
    identities = ProximityIdentity.objects.filter(session=session).filter(
        # Active, or retired recently enough to still resolve.
        Q(active=True) | Q(retired_at__gte=now - window),
    ).select_related('player')
    return {identity.token: identity for identity in identities}


def report_rate_exceeded(session, player, now=None):
    """True when `player` has already reported implausibly often.

    More than REPORT_RATE_BURST reports inside one effective report
    interval is "a rate far above the configured cadence" — the API
    layer maps this to HTTP 429.
    """
    now = now or timezone.now()
    interval = timedelta(seconds=session.effective('ble_report_interval_seconds'))
    recent = ProximityReport.objects.filter(
        session=session, player=player, received_at__gte=now - interval,
    ).count()
    return recent >= REPORT_RATE_BURST


def derive_proximity(session, now=None):
    """One derivation pass: fresh reports → ProximityEvents (persisted).

    - Only the latest report per player inside the freshness window
      counts; stale/absent reporters contribute nothing ("no observation
      this window", never fabricated proximity).
    - Plausibility filters: impossible crowds are dropped wholesale;
      unknown/expired tokens and self-sightings are skipped while the
      rest of the batch is kept.
    - Both directions of a pair fuse into ONE event: the bucket comes
      from the strongest reading, and confidence is boosted when both
      phones corroborate each other.
    - Hysteresis compares against the pair's most recent bucket from the
      recent past (≤ 2 freshness windows old).
    """
    now = now or timezone.now()
    window_seconds = session.effective('ble_freshness_window_seconds')
    window = timedelta(seconds=window_seconds)
    cutoff = now - window

    reports = (
        ProximityReport.objects
        .filter(session=session, received_at__gte=cutoff, received_at__lte=now)
        .order_by('player_id', '-received_at')
    )
    latest_by_player = {}
    for report in reports:
        latest_by_player.setdefault(report.player_id, report)

    token_map = resolvable_identities(session, now=now)

    # pair (lo, hi) → {'rssi': best, 'directions': {reporter ids}}
    evidence = {}
    for player_id, report in latest_by_player.items():
        observations = report.observations
        if len(observations) > MAX_PLAUSIBLE_CONTACTS:
            # Impossible crowd: this phone's claims are implausible as a
            # whole — exclude the report, keep everyone else's.
            continue
        for entry in observations:
            identity = token_map.get(entry.get('token'))
            if identity is None:
                continue  # unknown or expired token
            seen_id = identity.player_id
            if seen_id == player_id:
                continue  # self-sighting
            pair = (min(player_id, seen_id), max(player_id, seen_id))
            slot = evidence.setdefault(pair, {'rssi': None, 'directions': set()})
            rssi = int(entry['rssi'])
            if slot['rssi'] is None or rssi > slot['rssi']:
                slot['rssi'] = rssi
            slot['directions'].add(player_id)

    if not evidence:
        return []

    # Previous bucket per pair, for hysteresis (recent events only).
    previous_events = (
        ProximityEvent.objects
        .filter(session=session, derived_at__gte=now - 2 * window, derived_at__lt=now)
        .order_by('derived_at')
    )
    previous_bucket = {}
    for event in previous_events:
        previous_bucket[(event.player_a_id, event.player_b_id)] = event.distance_bucket

    very_close = session.effective('ble_rssi_very_close_dbm')
    near = session.effective('ble_rssi_near_dbm')
    hysteresis = session.effective('ble_rssi_hysteresis_db')

    events = []
    for (lo, hi), slot in sorted(evidence.items()):
        corroborated = len(slot['directions']) >= 2
        bucket = rssi_to_bucket(
            slot['rssi'],
            very_close_dbm=very_close,
            near_dbm=near,
            hysteresis_db=hysteresis,
            previous=previous_bucket.get((lo, hi)),
        )
        events.append(ProximityEvent(
            session=session,
            player_a_id=lo,
            player_b_id=hi,
            distance_bucket=bucket,
            confidence=CONFIDENCE_CORROBORATED if corroborated else CONFIDENCE_ONE_WAY,
            corroborated=corroborated,
            derived_at=now,
        ))
    return ProximityEvent.objects.bulk_create(events)
