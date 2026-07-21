"""Realtime event emission (realtime-and-notifications).

The single seam between business code and the transport layers:

- Business code (models, transition engine) calls the `emit_*` helpers
  below and NEVER imports Channels directly.
- Every websocket message is the typed envelope
  `{type, session, ts, payload}` with `type` one of the EVENT_*
  constants; clients dispatch on `type` and ignore unrecognised types.
- Fan-out targets one channel-layer group per Session
  (`session_<id>`), so events never leak across Sessions.
- When no channel layer is configured (or a send fails), emission
  degrades to a logged no-op — the REST/polling path stays authoritative
  and gameplay never depends on a broadcast landing.
- Capture/bonus emits also hand off to the opt-in push-notification
  path (`organize.push`); push failures are likewise swallowed.

`scoreboard.updated` is coalesced to at most one broadcast per
`settings.REALTIME_SCOREBOARD_THROTTLE_SECONDS` per Session (leading
edge). Because each event carries a FULL totals snapshot, dropping
intermediate events during a burst is safe; clients reconcile from a
REST snapshot on (re)connect and via the polling fallback.
"""

import logging
import time
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from django.conf import settings

logger = logging.getLogger(__name__)

EVENT_TOWER_OWNERSHIP_CHANGED = 'tower.ownership_changed'
EVENT_ZONE_CONTROL_CHANGED = 'zone.control_changed'
EVENT_SCOREBOARD_UPDATED = 'scoreboard.updated'
EVENT_BONUS_APPEARED = 'bonus.appeared'
# Extension beyond the four design.md map/score events: lifecycle
# transitions are broadcast too so clients can react (pause banners,
# snapshot refetch) without polling. Clients ignore unknown types.
EVENT_SESSION_STATE_CHANGED = 'session.state_changed'
# mode-dementors-ble 5.3: after each server economy tick, push a full
# role/energy snapshot so players see their own drain/gain and staff see
# live totals without waiting for the next poll. Coalesced like the
# scoreboard (each event is a full snapshot; dropping intermediates is
# safe), and clients still reconcile from REST on (re)connect.
EVENT_DEMENTOR_TICK = 'dementor.tick'

# Leading-edge throttle bookkeeping for coalesced broadcasts.
_scoreboard_last_sent = {}
_dementor_last_sent = {}


def session_group(session_id):
    """Channel-layer group name for a Session."""
    return f'session_{session_id}'


def reset_throttle():
    """Test hook: forget coalesced-broadcast throttle timestamps."""
    _scoreboard_last_sent.clear()
    _dementor_last_sent.clear()


def _channel_layer():
    try:
        from channels.layers import get_channel_layer
        return get_channel_layer()
    except Exception:  # pragma: no cover - channels missing/misconfigured
        return None


def broadcast_session_event(session_id, event_type, payload):
    """Fan a typed envelope out to the Session group.

    No-op (log + degrade) when the channel layer is unavailable or the
    send fails: realtime is an augmentation, never a correctness
    dependency.
    """
    layer = _channel_layer()
    if layer is None:
        logger.debug(
            'No channel layer; dropping %s for session %s', event_type, session_id,
        )
        return False
    envelope = {
        'type': event_type,
        'session': session_id,
        'ts': datetime.now(timezone.utc).isoformat(),
        'payload': payload,
    }
    try:
        async_to_sync(layer.group_send)(
            session_group(session_id),
            {'type': 'session.event', 'envelope': envelope},
        )
    except Exception:
        logger.warning(
            'Failed to broadcast %s for session %s', event_type, session_id,
            exc_info=True,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _team_summary(team):
    if team is None:
        return None
    return {'team_id': team.id, 'team_name': team.name, 'team_color': team.color}


def _tower_ownership_by_group(session, tower):
    """Per-TeamGroup controlling team for `tower`, keyed by group slug.

    Filter-based (newest open ownership wins) rather than
    `tower_control()`'s `.get()` so a stray duplicate open ownership can
    never break a capture broadcast.
    """
    from game.models import TeamTowerOwnership

    ownership = {}
    for group in session.game.teamgroup_set.all():
        row = (
            TeamTowerOwnership.objects
            .filter(tower=tower, timestamp_end__isnull=True, team__group=group)
            .select_related('team')
            .order_by('-timestamp_start')
            .first()
        )
        ownership[group.slug] = _team_summary(row.team if row else None)
    return ownership


def _zone_colors_by_group(session, zone):
    """Per-TeamGroup zone coloring, mirroring ZoneSerializer.get_team_color."""
    from organize.models import Team

    colors = {}
    for group in session.game.teamgroup_set.all():
        control_team_ids = list(zone.zone_control(group=group))
        teams = Team.objects.filter(pk__in=control_team_ids)
        if len(control_team_ids) > 1:
            color = '#FFFFFF'
        elif len(control_team_ids) == 1 and teams:
            color = teams[0].color
        else:
            color = '#000000'
        colors[group.slug] = color
    return colors


def _scoreboard_entries(session):
    """Every team's locked + floating totals, best first.

    Same entry shape as `SessionScoreboardView` so clients reuse their
    REST parsing.
    """
    entries = [
        {
            'team_id': team.id,
            'team_name': team.name,
            'team_color': team.color,
            'group_name': team.group.name if team.group else None,
            'group_slug': team.group.slug if team.group else None,
            'locked_score': team.score,
            'floating_score': round(team.floating_score(), 2),
            'current_score': team.current_score(),
        }
        for team in session.teams.select_related('group').order_by('name')
    ]
    entries.sort(key=lambda e: (-e['current_score'], e['team_name']))
    return entries


# ---------------------------------------------------------------------------
# Emit helpers (called from business code)
# ---------------------------------------------------------------------------


def emit_tower_ownership_changed(session, tower, *, team=None, kind='conquered'):
    """Broadcast a capture / steal / release, then hand off to push.

    `kind` is 'conquered' (previously unheld by this group), 'stolen'
    (taken from another team) or 'released' (tower deactivated /
    unassigned; `team` is None).
    """
    # tower-zone-topology: a tower may belong to several zones. The
    # first member zone keeps the legacy single zone_id/zone_name
    # contract; `zone_ids` carries the full membership.
    zones = list(tower.zones.order_by('pk'))
    payload = {
        'tower_id': tower.id,
        'tower_name': tower.name,
        'zone_id': zones[0].id if zones else None,
        'zone_name': zones[0].name if zones else None,
        'zone_ids': [zone.id for zone in zones],
        'kind': kind,
        'team': _team_summary(team),
        'ownership': _tower_ownership_by_group(session, tower),
    }
    broadcast_session_event(session.id, EVENT_TOWER_OWNERSHIP_CHANGED, payload)
    if kind in ('conquered', 'stolen') and team is not None:
        # The push module speaks 'conquer' / 'steal' (its PUSH_EVENTS
        # vocabulary and per-event preference toggles).
        push_event = 'steal' if kind == 'stolen' else 'conquer'
        _notify_push(session, push_event, tower=tower, team=team)


def emit_zone_control_changed(session, zone):
    """Broadcast a zone recolor after a control recompute."""
    payload = {
        'zone_id': zone.id,
        'zone_name': zone.name,
        'colors': _zone_colors_by_group(session, zone),
    }
    broadcast_session_event(session.id, EVENT_ZONE_CONTROL_CHANGED, payload)


def emit_scoreboard_update(session, *, force=False):
    """Broadcast every team's totals, throttled per Session.

    At most one broadcast per REALTIME_SCOREBOARD_THROTTLE_SECONDS per
    Session (`force=True` bypasses). Safe to drop intermediates: each
    event is a full snapshot.
    """
    window = getattr(settings, 'REALTIME_SCOREBOARD_THROTTLE_SECONDS', 2.0)
    if not force and window > 0:
        now = time.monotonic()
        last = _scoreboard_last_sent.get(session.id)
        if last is not None and (now - last) < window:
            return False
        _scoreboard_last_sent[session.id] = now
    return broadcast_session_event(
        session.id, EVENT_SCOREBOARD_UPDATED, {'entries': _scoreboard_entries(session)},
    )


def _dementor_snapshot(session):
    """Live role totals + a compact per-player role/energy list.

    Mirrors `StaffDementorTotalsView`'s numbers (minus the per-request
    username/team join, which stays a REST concern): the staff dashboard
    shows the totals live and reconciles the full feed from REST, and
    each player's client picks its own entry by `player_id`.
    """
    from game.models import DementorState

    states = list(
        DementorState.objects
        .filter(session=session)
        .order_by('player_id')
    )
    wizards = sum(
        1 for s in states if s.alive and s.role == DementorState.WIZARD
    )
    dementors = sum(
        1 for s in states if s.alive and s.role == DementorState.DEMENTOR
    )
    out_of_play = sum(1 for s in states if not s.alive)
    return {
        'totals': {
            'wizards': wizards,
            'dementors': dementors,
            'out_of_play': out_of_play,
        },
        'players': [
            {
                'player_id': s.player_id,
                'role': s.role,
                'energy': round(s.energy, 2),
                'alive': s.alive,
                'last_delta': round(s.last_delta, 3),
            }
            for s in states
        ],
    }


def emit_dementor_tick(session, *, force=False):
    """Broadcast a role/energy snapshot after an economy tick, throttled.

    At most one broadcast per REALTIME_DEMENTOR_THROTTLE_SECONDS per
    Session (`force=True` bypasses). Safe to coalesce: every event is a
    full snapshot and clients reconcile from REST on (re)connect.
    """
    window = getattr(settings, 'REALTIME_DEMENTOR_THROTTLE_SECONDS', 2.0)
    if not force and window > 0:
        now = time.monotonic()
        last = _dementor_last_sent.get(session.id)
        if last is not None and (now - last) < window:
            return False
        _dementor_last_sent[session.id] = now
    return broadcast_session_event(
        session.id, EVENT_DEMENTOR_TICK, _dementor_snapshot(session),
    )


def emit_bonus_appeared(session, payload):
    """Broadcast a bonus / score-multiplier appearance, then push.

    Seam for the `score-multipliers` capability: when a bonus activates
    it calls this with a descriptive payload (what the bonus is and
    where it applies). No call site exists in this change — the
    multiplier engine lands with the score-multipliers change.
    """
    broadcast_session_event(session.id, EVENT_BONUS_APPEARED, payload)
    _notify_push(session, 'bonus', payload=payload)


def emit_session_state_changed(session, *, previous, action):
    """Broadcast a lifecycle transition (start / pause / resume / finish)."""
    broadcast_session_event(session.id, EVENT_SESSION_STATE_CHANGED, {
        'state': session.state,
        'previous': previous,
        'action': action,
        'is_active': session.is_active,
    })


def _notify_push(session, event, **context):
    """Hand off to the opt-in push path; never let it break gameplay."""
    try:
        from organize.push import notify_session_event
        notify_session_event(session, event, **context)
    except Exception:
        logger.warning(
            'Push notification hand-off failed for session %s (%s)',
            session.id, event, exc_info=True,
        )
