"""Live overview snapshot (live-overview capability).

One response describing where a Session stands *right now*: towers with
their current owner, zones with their current controller, standings, the
recent captures, and — only where the Session's configuration permits it
on a shared surface — player positions.

Deliberately separate from `game.replay`. The replay bundle is a whole
window of history with frames and intervals; this is a single instant
with none. Collapsing them would give one function two modes and no
clear contract. What they do share is field naming for teams, towers and
zones, so both map surfaces paint from the same shapes.

Ownership here is per-TeamGroup, matching the domain: several groups
play the same map at once, so a tower has one owner *per group*, not one
owner. The payload therefore keys ownership and zone colours by group
slug exactly as the realtime events do (`game.events`), which is what
lets a client apply a `tower.ownership_changed` envelope straight onto a
snapshot without reshaping it.
"""

from django.utils import timezone

from game.events import (
    _scoreboard_entries,
    _tower_ownership_by_group,
    _zone_colors_by_group,
)
from game.location_api import tracking_enabled
from game.models import LocationConsent, LocationPing, TeamTowerOwnership
from organize.models import (
    LOCATION_VISIBILITY_EVERYONE,
    LOCATION_VISIBILITY_OWN_TEAM,
    TEAMMATE_VISIBILITY_SELECT_COUNT,
)

# How many recent captures the ticker carries.
RECENT_EVENT_LIMIT = 12

# Why the overview is not plotting anyone. Codes rather than prose so the
# client can phrase it; every one of them means "show the map without
# dots", never "show an empty map".
REASON_TRACKING_DISABLED = 'TRACKING_DISABLED'
REASON_VISIBILITY_NONE = 'VISIBILITY_NONE'
REASON_VISIBILITY_OWN_TEAM = 'VISIBILITY_OWN_TEAM'
REASON_VISIBILITY_NEAREST_ONLY = 'VISIBILITY_NEAREST_ONLY'


def position_visibility(session):
    """Whether a *shared* surface may plot positions, and why not.

    The rule that distinguishes this capability. `visible_live_pings()`
    hands staff every consenting player regardless of
    `location_visibility`, which is right for one accountable person
    reading their own console and wrong for a screen a room is reading —
    and, with a share link, for a caller who has no account at all.

    `OWN_TEAM` and `SELECT_COUNT` are both *caller-relative*: "each
    viewer sees their own team", "each viewer sees the N nearest to
    them". Neither has a meaning where there is no single viewer, and
    the only two ways to resolve that are to show everything or to show
    nothing. Showing everything inverts what the setting was chosen for,
    so a shared surface shows nothing and says so.

    Returns `(allowed, reason)`; `reason` is None when allowed.
    """
    if not tracking_enabled(session):
        return False, REASON_TRACKING_DISABLED
    visibility = session.effective('location_visibility')
    if visibility != LOCATION_VISIBILITY_EVERYONE:
        return False, (
            REASON_VISIBILITY_OWN_TEAM
            if visibility == LOCATION_VISIBILITY_OWN_TEAM
            else REASON_VISIBILITY_NONE
        )
    if session.effective('teammate_visibility_mode') == TEAMMATE_VISIBILITY_SELECT_COUNT:
        return False, REASON_VISIBILITY_NEAREST_ONLY
    return True, None


def _groups(session):
    return [
        {'slug': group.slug, 'name': group.name}
        for group in session.game.teamgroup_set.order_by('name')
    ]


def _teams(session):
    return [{
        'id': team.id,
        'name': team.name,
        'color': team.color,
        'group_slug': team.group.slug if team.group else None,
    } for team in session.teams.select_related('group').order_by('name')]


def _towers(session):
    towers = session.towers().prefetch_related('zones').order_by('id')
    return [{
        'id': tower.id,
        'name': tower.name,
        'lat': tower.location.y,
        'lng': tower.location.x,
        'ownership': _tower_ownership_by_group(session, tower),
    } for tower in towers]


def _zones(session):
    return [{
        'id': zone.id,
        'name': zone.name,
        'shape': zone.shape.geojson if zone.shape else None,
        'colors': _zone_colors_by_group(session, zone),
    } for zone in session.zones().order_by('id')]


def _recent_events(session, limit=RECENT_EVENT_LIMIT):
    """The last few ownership changes, newest first.

    Read from `TeamTowerOwnership` starts rather than from a broadcast
    log: the broadcasts are fire-and-forget, so a screen that connects
    mid-game would otherwise open with an empty ticker and only fill as
    the next capture happens.
    """
    rows = (
        TeamTowerOwnership.objects
        .filter(team__session=session)
        .select_related('team', 'team__group', 'tower')
        .order_by('-timestamp_start', '-id')[:limit]
    )
    return [{
        'tower_id': row.tower_id,
        'tower_name': row.tower.name,
        'team_id': row.team_id,
        'team_name': row.team.name,
        'team_color': row.team.color,
        'group_slug': row.team.group.slug if row.team.group else None,
        'at': row.timestamp_start,
        'still_held': row.timestamp_end is None,
    } for row in rows]


def _positions(session, *, with_names):
    """Latest consenting position per player, or an explained absence."""
    allowed, reason = position_visibility(session)
    if not allowed:
        return {'visible': False, 'reason': reason, 'items': []}
    consenting = LocationConsent.objects.filter(
        session=session, withdrawn_at__isnull=True,
    ).values_list('user_id', flat=True)
    pings = (
        LocationPing.objects
        .latest_per_user(session)
        .filter(user_id__in=consenting)
        .select_related('user', 'team')
    )
    items = []
    for ping in pings:
        item = {
            'user_id': ping.user_id,
            'team_id': ping.team_id,
            'team_name': ping.team.name if ping.team else None,
            'team_color': ping.team.color if ping.team else None,
            'lat': ping.point.y,
            'lng': ping.point.x,
            'accuracy': ping.accuracy,
            'recorded_at': ping.recorded_at,
        }
        # A name is useful to a staff member deciding who to radio and
        # merely identifying on a projector nobody is accountable for,
        # so the share snapshot carries the dot and the colour only.
        if with_names:
            item['username'] = ping.user.username
        items.append(item)
    return {'visible': True, 'reason': None, 'items': items}


def build_overview_snapshot(session, *, with_names=True):
    """Everything the live overview renders, at this instant."""
    from game.multipliers_api import active_multiplier_payload

    return {
        'session': {
            'id': session.id,
            'name': session.name,
            'slug': session.slug,
            'state': session.state,
            'state_label': session.get_state_display(),
            'game_name': session.game.name,
            'game_slug': session.game.slug,
            'start_time': session.start_time,
            'end_time': session.end_time,
        },
        'generated_at': timezone.now(),
        'groups': _groups(session),
        'teams': _teams(session),
        'towers': _towers(session),
        'zones': _zones(session),
        'standings': _scoreboard_entries(session),
        'active_multipliers': active_multiplier_payload(session),
        'events': _recent_events(session),
        'positions': _positions(session, with_names=with_names),
    }
