"""Replay bundle assembly for a recorded Session (session-replay capability).

A *replay* is an ordered series of frames, each a full snapshot of the
game world at one instant. This module builds the **bundle** a client
needs to project those frames itself: roster, teams, tower/zone
geometry, tower-ownership intervals, and player positions already
downsampled to one sample per player per frame.

The split is deliberate (see the change's design.md): bucketing happens
here because it is what bounds payload size, and Postgres `DISTINCT ON`
does it far better than JS; frame assembly happens in the browser
because that is what keeps scrubbing instant. The same client-side
projection serves the simulator's tick tape, so replay semantics have
one implementation rather than two.

Nothing here is persisted and nothing is mutated — every input is
already recorded by the live game: `LocationPing` (live-location),
`TeamTowerOwnership` (a start/end interval table, so ownership at any
instant is exact rather than reconstructed), `Team`, `Tower`, `Zone`.
"""
from datetime import timedelta

from django.db.models import FloatField, IntegerField, Q, Value
from django.db.models.functions import Cast, Extract, Floor
from django.utils import timezone

from game.models import LocationConsent, LocationPing, TeamTowerOwnership

# Frame-interval bounds. The floor stops a caller asking for per-second
# frames over a three-hour session; the cap coarsens rather than
# truncates, so a long session stays replayable end to end.
MIN_INTERVAL_SECONDS = 5
DEFAULT_INTERVAL_SECONDS = 30
MAX_FRAMES = 2000

# A client-supplied `recorded_at` this far outside the Session window is
# treated as a skewed or replayed clock and excluded from frames.
WINDOW_GRACE = timedelta(minutes=30)


def resolve_interval(requested, span_seconds):
    """Frame width to use, honouring the floor and the frame cap.

    Returns `(interval_seconds, coarsened)`; `coarsened` is True when
    the cap forced a wider interval than asked for, which the response
    reports so the caller knows the timeline is coarser than requested.
    """
    try:
        interval = int(requested) if requested else DEFAULT_INTERVAL_SECONDS
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_SECONDS
    interval = max(MIN_INTERVAL_SECONDS, interval)
    if span_seconds <= 0:
        return interval, False
    if _ceil_div(span_seconds, interval) <= MAX_FRAMES:
        return interval, False
    return max(interval, _ceil_div(span_seconds, MAX_FRAMES)), True


def _ceil_div(numerator, denominator):
    return -(-numerator // denominator)


def _window(session, window_from, window_to):
    """The replay window: caller bounds clamped into the Session's own."""
    start, end = session.start_time, session.end_time
    if window_from and window_from > start:
        start = window_from
    if window_to and window_to < end:
        end = window_to
    return start, max(end, start)


def _bucket_expression(start, interval):
    """Frame ordinal of a ping: floor((recorded_at - start) / interval).

    Kept in floating-point seconds all the way to an explicit `FLOOR`.
    Casting the epoch to an integer first would be wrong: Postgres
    `CAST(... AS integer)` *rounds*, so a window start carrying more
    than half a second of microseconds would push every ping into the
    next frame — an off-by-one that depends on the wall clock and so
    shows up only intermittently.
    """
    elapsed = Extract('recorded_at', 'epoch') - Value(
        start.timestamp(), output_field=FloatField(),
    )
    return Cast(
        Floor(elapsed / Value(float(interval), output_field=FloatField())),
        IntegerField(),
    )


def _bucket_pings(session, start, end, interval, frame_count):
    """One position per player per frame, newest-in-bucket wins.

    `DISTINCT ON (user, bucket)` does the downsampling in the database.
    Samples whose client clock lands outside the Session window by more
    than `WINDOW_GRACE` are dropped as implausible before bucketing.
    """
    pings = (
        LocationPing.objects
        .filter(session=session, recorded_at__gte=start, recorded_at__lte=end)
        .filter(
            recorded_at__gte=session.start_time - WINDOW_GRACE,
            recorded_at__lte=session.end_time + WINDOW_GRACE,
        )
        .annotate(frame=_bucket_expression(start, interval))
        # DISTINCT ON needs its columns to lead ORDER BY; the trailing
        # -recorded_at then picks the newest sample inside each bucket.
        .order_by('user_id', 'frame', '-recorded_at')
        .distinct('user_id', 'frame')
    )
    rows = [{
        'user_id': ping.user_id,
        # Clamp so a sample landing exactly on `end` cannot index one
        # past the declared timeline.
        'frame': min(int(ping.frame), frame_count - 1),
        'lat': ping.point.y,
        'lng': ping.point.x,
        'accuracy': ping.accuracy,
        'recorded_at': ping.recorded_at,
        'received_at': ping.received_at,
    } for ping in pings]
    rows.sort(key=lambda row: (row['frame'], row['user_id']))
    return rows


def _ownership_intervals(session, start, end):
    """Ownership rows overlapping the window — not merely starting in it.

    An interval that began before `start` and had not ended is what
    makes frame 0 show the towers a team already held, instead of an
    empty map that fills in only as captures happen.
    """
    rows = (
        TeamTowerOwnership.objects
        .filter(team__session=session, timestamp_start__lte=end)
        .filter(Q(timestamp_end__isnull=True) | Q(timestamp_end__gte=start))
        .select_related('team')
        .order_by('timestamp_start', 'id')
    )
    return [{
        'tower_id': row.tower_id,
        'team_id': row.team_id,
        'start': row.timestamp_start,
        'end': row.timestamp_end,
    } for row in rows]


def _effective(session, field):
    """`Session.effective`, tolerating a field this deployment lacks."""
    try:
        return session.effective(field)
    except (ValueError, AttributeError):
        return None


def _availability(session, start):
    """Why a replay may be thinner than the roster suggests.

    Location data is partial by construction — tracking can be off,
    players may never have consented or may have withdrawn (which
    purges their pings), and retention purges the series on a timer.
    The view states this rather than rendering a silently empty map.
    """
    retention_days = _effective(session, 'location_retention_days')
    consented = (
        LocationConsent.objects
        .filter(session=session, withdrawn_at__isnull=True)
        .values('user_id')
        .distinct()
        .count()
    )
    earliest = (
        LocationPing.objects
        .filter(session=session)
        .order_by('recorded_at')
        .values_list('recorded_at', flat=True)
        .first()
    )
    retention_cutoff = (
        timezone.now() - timedelta(days=int(retention_days)) if retention_days else None
    )
    return {
        'location_tracking_enabled': bool(_effective(session, 'location_tracking_enabled')),
        'consented_players': consented,
        'roster_players': _roster_size(session),
        'retention_days': retention_days,
        'retention_cutoff': retention_cutoff,
        'earliest_ping_at': earliest,
        # True when the window reaches back past the retention cutoff, so
        # part of it either has been or is about to be purged; the
        # timeline marks that span rather than presenting what survives
        # as the whole session.
        #
        # Deliberately NOT "the first surviving ping is later than the
        # window start" — that is true of almost every session, since
        # nobody pings at the instant a session opens, and it would cry
        # purge on sessions whose history is perfectly intact.
        'history_truncated': bool(retention_cutoff and start < retention_cutoff),
    }


def _roster_size(session):
    from organize.models import TeamMembership
    return (
        TeamMembership.objects
        .filter(team__session=session)
        .values('user__user_id')
        .distinct()
        .count()
    )


def _players(session):
    """The Session roster, including players whose membership has ended.

    A replay of who was where must not drop someone who left their team
    mid-game; `LocationPing.team` is denormalized at ingest for the same
    reason.

    Keyed by the **auth user** id, not the profile id, because that is
    what `LocationPing.user` records and therefore the join key a client
    needs to match a position back to a player.
    """
    from organize.models import TeamMembership
    rows = (
        TeamMembership.objects
        .filter(team__session=session)
        .select_related('user__user', 'team')
        # Newest membership first, so a player who changed teams is
        # listed under the team they ended on.
        .order_by('user__user_id', '-id')
    )
    players = {}
    for row in rows:
        players.setdefault(row.user.user_id, {
            'user_id': row.user.user_id,
            'username': row.user.user.username,
            'team_id': row.team_id,
            'team_name': row.team.name,
        })
    return list(players.values())


def build_replay_bundle(session, *, interval_seconds=None, window_from=None, window_to=None):
    """Everything needed to replay `session`, in one response."""
    start, end = _window(session, window_from, window_to)
    span = max(0, int((end - start).total_seconds()))
    interval, coarsened = resolve_interval(interval_seconds, span)
    frame_count = _ceil_div(span, interval) + 1 if span else 1

    return {
        'session': {
            'id': session.id,
            'name': session.name,
            'state': session.state,
            'start_time': session.start_time,
            'end_time': session.end_time,
        },
        'window': {'from': start, 'to': end},
        'interval_seconds': interval,
        'interval_coarsened': coarsened,
        'frame_count': frame_count,
        'teams': [{
            'id': team.id,
            'name': team.name,
            'color': team.color,
            'group_id': team.group_id,
        } for team in session.teams.order_by('id')],
        'players': _players(session),
        'towers': [{
            'id': tower.id,
            'name': tower.name,
            'lat': tower.location.y,
            'lng': tower.location.x,
        } for tower in session.towers().order_by('id')],
        'zones': [{
            'id': zone.id,
            'name': zone.name,
            'shape': zone.shape.geojson if zone.shape else None,
        } for zone in session.zones().order_by('id')],
        'ownership': _ownership_intervals(session, start, end),
        'positions': _bucket_pings(session, start, end, interval, frame_count),
        'availability': _availability(session, start),
    }
