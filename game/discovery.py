"""Tower discovery mechanics (discovery-tracking capability).

One evaluation routine drives every reveal, whatever the position
source (the live-location ping stream or the self-contained
`POST /api/discovery/ping/` fallback):

- `HIDDEN` towers reveal when a member's position falls within the
  tower's effective `proximity_meters` (`PROXIMITY`).
- `FOG_REVEAL` towers reveal when a member's position falls inside one
  of the tower's zones (`ZONE_ENTRY`), or when the team's accumulated
  buffered-visited coverage of that zone crosses the zone's effective
  `fog_reveal_coverage_pct` (`ZONE_COVERAGE`).

Visibility resolution ("which towers/zones may this team see") lives
here too so the map endpoints and `Session.visible_towers(team)` share
one implementation. Discovery is append-only: rows are never deleted on
conquest or loss of ownership.
"""
from django.contrib.gis.measure import Distance as DistanceMeasure
from django.db.models import Q

from game.models import (
    TeamZoneCoverage,
    Tower,
    TowerDiscovery,
    effective_discoverability,
    effective_fog_reveal_pct,
    effective_proximity,
)
from organize.models import (
    DISCOVERABILITY_FOG_REVEAL,
    DISCOVERABILITY_HIDDEN,
    DISCOVERABILITY_VISIBLE,
)

# Radius (meters) a single reported position is considered to have
# "visited" for fog-of-war coverage accumulation. Deliberately a module
# constant, not a per-game knob: it is a resolution/cost tradeoff of the
# coverage computation, not a gameplay rule.
COVERAGE_BUFFER_METERS = 50


def _visible_now_q(default):
    """Q filter: towers whose EFFECTIVE discoverability is VISIBLE.

    A null (or blank) per-tower value resolves to the session's
    effective default, so the null rows count as visible exactly when
    the default itself is VISIBLE.
    """
    explicit = Q(discoverability=DISCOVERABILITY_VISIBLE)
    if default == DISCOVERABILITY_VISIBLE:
        return explicit | Q(discoverability__isnull=True) | Q(discoverability='')
    return explicit


def discovered_tower_ids(session, team):
    """Ids of the towers `team` has discovered in `session`."""
    return TowerDiscovery.objects.filter(
        session=session, team=team,
    ).values_list('tower_id', flat=True)


def visible_towers(session, team):
    """Towers `team` may see: effective-VISIBLE ones plus discovered ones.

    Computed entirely independently of ownership (a discovered tower
    stays visible after being conquered by others or going ownerless —
    the TowerDiscovery row persists).
    """
    default = session.effective('tower_discoverability_default')
    return session.towers().filter(
        _visible_now_q(default) | Q(pk__in=discovered_tower_ids(session, team)),
    )


def visible_zone_ids(session, team):
    """Ids of the zones `team` may see in `session`.

    Only `FOG_REVEAL` fogs the zone itself: a zone is hidden exactly
    when EVERY member tower's effective discoverability is FOG_REVEAL
    and the team has discovered none of them. A `HIDDEN` tower's zone
    may still be drawn (design non-goal), so any non-fog member tower —
    or any discovered one — makes the zone visible.
    """
    default = session.effective('tower_discoverability_default')
    discovered = set(discovered_tower_ids(session, team))
    visible = []
    for zone in session.zones().prefetch_related('towers'):
        members = list(zone.towers.all())
        if not members:
            # Empty zones are filtered elsewhere (at-least-one-tower
            # invariant); never hide them here.
            visible.append(zone.pk)
            continue
        for tower in members:
            effective = tower.discoverability or default
            if effective != DISCOVERABILITY_FOG_REVEAL or tower.pk in discovered:
                visible.append(zone.pk)
                break
    return visible


def _record(session, team, tower, method, user, created_rows):
    """Idempotently create one TowerDiscovery; collect newly created rows."""
    discovery, created = TowerDiscovery.objects.get_or_create(
        session=session,
        team=team,
        tower=tower,
        defaults={'method': method, 'discovered_by': user},
    )
    if created:
        created_rows.append(discovery)
    return discovery


def staff_reveal(team, tower, user=None):
    """Staff override: reveal `tower` to `team` as if discovered in the field."""
    discovery, _created = TowerDiscovery.objects.get_or_create(
        session=team.session,
        team=team,
        tower=tower,
        defaults={'method': TowerDiscovery.METHOD_STAFF, 'discovered_by': user},
    )
    return discovery


def _buffered(point, meters):
    """Buffer a 4326 point by `meters` (buffered in 3857, returned in 4326)."""
    projected = point.clone()
    if projected.srid is None:
        projected.srid = 4326
    projected.transform(3857)
    circle = projected.buffer(meters)
    circle.transform(4326)
    return circle


def _coverage_pct(visited, zone_shape):
    """area(visited ∩ zone) / area(zone), in percent (computed in 3857)."""
    zone_projected = zone_shape.transform(3857, clone=True)
    visited_projected = visited.transform(3857, clone=True)
    if not zone_projected.area:
        return 0.0
    covered = visited_projected.intersection(zone_projected)
    return covered.area / zone_projected.area * 100.0


def _accumulate_coverage(session, team, zone, point):
    """Fold one position into the team's coverage of `zone`; return the row.

    Short-circuits once `revealed` is set — after the threshold is
    crossed no further geometry is accumulated for the pair.
    """
    coverage, _created = TeamZoneCoverage.objects.get_or_create(
        session=session, team=team, zone=zone,
    )
    if coverage.revealed or zone.shape is None:
        return coverage
    circle = _buffered(point, COVERAGE_BUFFER_METERS)
    visited = circle if coverage.visited is None else coverage.visited.union(circle)
    coverage.visited = visited
    coverage.coverage_pct = _coverage_pct(visited, zone.shape)
    if coverage.coverage_pct > effective_fog_reveal_pct(zone, session=session):
        coverage.revealed = True
    coverage.save()
    return coverage


def evaluate_discovery(session, team, point, user=None):
    """Evaluate every reveal trigger for one reported position.

    Returns the list of NEWLY created TowerDiscovery rows (already-known
    towers never re-reveal — the unique (session, team, tower) row is
    append-only). Both position sources — the live-location ping stream
    and the discovery-ping fallback — funnel through this routine so
    they create discoveries identically.
    """
    if point.srid is None:
        point.srid = 4326
    game = session.game
    already = set(discovered_tower_ids(session, team))
    candidates = (
        session.towers()
        .filter(is_active=True)
        .exclude(pk__in=already)
        .prefetch_related('zones')
    )

    new_rows = []
    fog_zones = {}  # zone -> [undiscovered FOG_REVEAL towers in it]
    for tower in candidates:
        effective = effective_discoverability(tower, session=session)
        if effective == DISCOVERABILITY_HIDDEN:
            radius = effective_proximity(tower, game)
            within = Tower.objects.filter(
                pk=tower.pk,
                location__distance_lte=(point, DistanceMeasure(m=radius)),
            ).exists()
            if within:
                _record(
                    session, team, tower,
                    TowerDiscovery.METHOD_PROXIMITY, user, new_rows,
                )
        elif effective == DISCOVERABILITY_FOG_REVEAL:
            for zone in tower.zones.all():
                fog_zones.setdefault(zone, []).append(tower)

    for zone, towers in fog_zones.items():
        if zone.shape is not None and zone.shape.contains(point):
            # Zone entry reveals immediately; coverage becomes moot.
            for tower in towers:
                _record(
                    session, team, tower,
                    TowerDiscovery.METHOD_ZONE_ENTRY, user, new_rows,
                )
            continue
        coverage = _accumulate_coverage(session, team, zone, point)
        if coverage.revealed:
            for tower in towers:
                _record(
                    session, team, tower,
                    TowerDiscovery.METHOD_ZONE_COVERAGE, user, new_rows,
                )
    return new_rows
