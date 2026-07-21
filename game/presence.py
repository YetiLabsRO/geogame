"""Presence resolution & evaluation (presence-rules capability).

Turns config (Session togetherness/window knobs + a Challenge's
optional `PresenceRequirement`) into an effective requirement, then
verifies it against the live-location ping stream:

- `resolve_presence(session, challenge, tower, team=None)` — the pure
  effective-requirement function (nothing stored; changing a knob
  mid-run takes effect immediately).
- `evaluate_presence(...)` — geofence co-presence counting, the
  continuous-tracking window (trajectory/duration), and the
  staff-reviewed photo fallback. Returns a `PresenceResult`.
- `presence_status_payload(...)` — the player-facing "required vs
  present" read for a tower.

The default resolution (no requirement, SPLIT_ALLOWED, window 0) is a
no-op: `resolve_presence(...)['is_noop']` is True and the submission
flow skips evaluation entirely, preserving base behaviour byte for
byte.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.contrib.gis.measure import Distance
from django.utils import timezone

from game.models import (
    PRESENCE_METHOD_GEOFENCE,
    PRESENCE_METHOD_GEOFENCE_OR_PHOTO,
    PRESENCE_METHOD_PHOTO,
    PRESENCE_REASON_INSUFFICIENT_MEMBERS,
    PRESENCE_REASON_MEMBER_OUTSIDE,
    PRESENCE_REASON_PHOTO_REVIEW,
    PRESENCE_REASON_WINDOW_NOT_SATISFIED,
    LocationPing,
)
from organize.models import TOGETHERNESS_WHOLE_TEAM, TeamMembership

# A member's latest ping counts as "fresh" within this multiple of the
# effective ping interval (bounded below), so one missed upload does
# not drop a genuinely-present teammate.
PING_FRESHNESS_FACTOR = 3
PING_FRESHNESS_MIN_SECONDS = 60


def resolve_presence(session, challenge, tower, team=None):
    """The effective presence requirement for a submission, as a dict.

    `{min_members, method, geofence_radius_meters, window_seconds,
    requirement, is_noop}` — resolved purely from config:

    - min_members: the team's active-membership count when the
      Session's effective togetherness is WHOLE_TEAM_TOGETHER (needs
      `team`; overrides any challenge minimum), else the requirement's
      `min_members_present` (default 1).
    - radius: requirement's `geofence_radius_meters`, else the tower's
      effective `proximity_meters` (the Game rule config).
    - window: requirement's `window_seconds`, else the Session's
      effective `presence_window_seconds`.

    `is_noop` marks the fully-default resolution (no requirement row,
    min 1, window 0): the submission flow imposes nothing beyond the
    submitter's own proximity check and writes no PresenceCheck.
    """
    requirement = challenge.presence_requirement if challenge is not None else None
    min_members = requirement.min_members_present if requirement is not None else 1
    method = requirement.method if requirement is not None else PRESENCE_METHOD_GEOFENCE

    radius = None
    if requirement is not None:
        radius = requirement.geofence_radius_meters
    if radius is None:
        radius = session.game.proximity_meters

    window = None
    if requirement is not None:
        window = requirement.window_seconds
    if window is None:
        window = session.effective('presence_window_seconds')

    whole_team = session.effective('togetherness_mode') == TOGETHERNESS_WHOLE_TEAM
    if whole_team and team is not None:
        min_members = max(min_members, team.active_member_count())

    return {
        'min_members': min_members,
        'method': method,
        'geofence_radius_meters': radius,
        'window_seconds': window,
        'requirement': requirement,
        'is_noop': requirement is None and not whole_team and window == 0,
    }


@dataclass
class PresenceResult:
    satisfied: bool
    reason_code: str = ''
    detail: str = ''
    method_used: str = PRESENCE_METHOD_GEOFENCE
    present_count: int = 0
    verified_member_ids: list = field(default_factory=list)
    # None = the window could not be evaluated (live-location
    # unavailable); True/False = evaluated outcome.
    window_satisfied: bool | None = None
    # True when the submission must be held PENDING for staff review
    # (photo fallback — never auto-confirmed).
    hold_for_review: bool = False


def _freshness_cutoff(session, now):
    interval = session.effective('location_ping_interval_seconds') or 30
    seconds = max(PING_FRESHNESS_FACTOR * interval, PING_FRESHNESS_MIN_SECONDS)
    return now - timedelta(seconds=seconds)


def _member_user_ids(team):
    """Active members' auth-user ids (TeamMembership.user is the profile)."""
    return list(
        TeamMembership.objects
        .filter(team=team, is_active=True)
        .values_list('user__user_id', flat=True)
    )


def _gis_inside(point, tower, radius):
    """Geodesic containment check via the DB (authoritative)."""
    from game.models import Tower
    return Tower.objects.filter(
        pk=tower.pk, location__distance_lte=(point, Distance(m=radius)),
    ).exists()


def _latest_pings(session, user_ids, cutoff):
    """{user_id: latest fresh LocationPing} for `user_ids` in `session`."""
    pings = (
        LocationPing.objects
        .latest_per_user(session)
        .filter(user_id__in=user_ids, recorded_at__gte=cutoff)
    )
    return {ping.user_id: ping for ping in pings}


def _window_pings(session, user_id, window_start, now):
    """The member's trajectory for the window, plus the boundary ping.

    Includes the last ping *before* the window start so "arrived at the
    fence only at the last instant" is caught: their position at the
    window's opening is part of the trajectory being judged.
    """
    in_window = list(
        LocationPing.objects.filter(
            session=session,
            user_id=user_id,
            recorded_at__gte=window_start,
            recorded_at__lte=now,
        )
    )
    boundary = (
        LocationPing.objects
        .filter(session=session, user_id=user_id, recorded_at__lt=window_start)
        .order_by('-recorded_at')
        .first()
    )
    if boundary is not None:
        in_window.append(boundary)
    return in_window


def _member_window_ok(session, user_id, tower, radius, window, now):
    """True/False when evaluable; None when the member has no window data."""
    pings = _window_pings(session, user_id, now - timedelta(seconds=window), now)
    if not pings:
        return None
    return all(
        _gis_inside(ping.point, tower, radius) for ping in pings
    )


def _geofence_presence(*, session, team, tower, submitter, submission_point,
                       radius, window, now):
    """Count verified-present members; returns (result, outside_seen).

    A member is present when their most recent ping is fresh and inside
    the geofence; the submitter always counts from their submission GPS
    (even with a stale ping). With window > 0 and ping data available,
    every counted member's trajectory across the window must stay
    inside the geofence.
    """
    tracking_on = bool(session.effective('location_tracking_enabled'))
    member_ids = _member_user_ids(team)
    cutoff = _freshness_cutoff(session, now)
    latest = _latest_pings(session, member_ids, cutoff) if tracking_on else {}

    verified = []
    outside_seen = False
    if submission_point is not None and _gis_inside(submission_point, tower, radius):
        verified.append(submitter.id)
    for user_id, ping in latest.items():
        if user_id == submitter.id:
            continue
        if _gis_inside(ping.point, tower, radius):
            verified.append(user_id)
        else:
            outside_seen = True

    window_satisfied = None
    dropped_by_window = False
    if window > 0:
        window_evaluable = tracking_on and LocationPing.objects.filter(
            session=session, user_id__in=member_ids,
        ).exists()
        if window_evaluable:
            kept = []
            for user_id in verified:
                ok = _member_window_ok(session, user_id, tower, radius, window, now)
                if ok is False:
                    dropped_by_window = True
                else:
                    # ok True, or None = no trajectory data for this
                    # member (e.g. the submitter with a stale/absent
                    # stream): degrade to point-in-time for them rather
                    # than punishing them.
                    kept.append(user_id)
            verified = kept
            # True = every *counted* member held the window; the
            # dropped ones are no longer counted.
            window_satisfied = True
        # else: live-location unavailable — point-in-time only, window
        # recorded as not evaluated (None).

    return verified, outside_seen, window_satisfied, dropped_by_window


def evaluate_presence(*, session, team, tower, submitter, submission_point,
                      resolved, has_photo=False, now=None):
    """Evaluate the resolved presence requirement for a submission."""
    now = now or timezone.now()
    required = resolved['min_members']
    radius = resolved['geofence_radius_meters']
    window = resolved['window_seconds']
    method = resolved['method']

    if method == PRESENCE_METHOD_PHOTO:
        # Photo-only: deliberately the weakest tier — never verified
        # automatically, always staff-reviewed.
        if has_photo:
            return PresenceResult(
                satisfied=True,
                reason_code=PRESENCE_REASON_PHOTO_REVIEW,
                detail='Photo evidence accepted; staff must confirm the required people.',
                method_used=PRESENCE_METHOD_PHOTO,
                present_count=1,
                verified_member_ids=[submitter.id],
                hold_for_review=True,
            )
        return PresenceResult(
            satisfied=False,
            reason_code=PRESENCE_REASON_PHOTO_REVIEW,
            detail=(
                f'This challenge requires a photo showing the {required} '
                'required member(s) together.'
            ),
            method_used=PRESENCE_METHOD_PHOTO,
        )

    verified, outside_seen, window_satisfied, dropped_by_window = _geofence_presence(
        session=session,
        team=team,
        tower=tower,
        submitter=submitter,
        submission_point=submission_point,
        radius=radius,
        window=window,
        now=now,
    )
    present = len(verified)
    if present >= required:
        return PresenceResult(
            satisfied=True,
            method_used=PRESENCE_METHOD_GEOFENCE,
            present_count=present,
            verified_member_ids=verified,
            window_satisfied=window_satisfied,
        )

    if dropped_by_window:
        window_satisfied = False
        reason = PRESENCE_REASON_WINDOW_NOT_SATISFIED
        detail = (
            f'Presence must be held for {window}s inside the geofence; a '
            'required member left (or arrived only at the last instant).'
        )
    elif outside_seen:
        reason = PRESENCE_REASON_MEMBER_OUTSIDE
        detail = 'A required member\'s live position is outside the geofence.'
    else:
        reason = PRESENCE_REASON_INSUFFICIENT_MEMBERS
        detail = (
            f'Only {present} of the required {required} member(s) are '
            'verified present at the tower.'
        )

    if method == PRESENCE_METHOD_GEOFENCE_OR_PHOTO and has_photo:
        # Geofence data was insufficient — fall back to the photo, held
        # for staff review (never auto-confirmed).
        return PresenceResult(
            satisfied=True,
            reason_code=PRESENCE_REASON_PHOTO_REVIEW,
            detail='Geofence insufficient; photo evidence held for staff review.',
            method_used=PRESENCE_METHOD_PHOTO,
            present_count=present,
            verified_member_ids=verified,
            window_satisfied=window_satisfied,
            hold_for_review=True,
        )

    if method == PRESENCE_METHOD_GEOFENCE_OR_PHOTO:
        detail += ' You may attach a photo of the required members instead (staff-reviewed).'

    return PresenceResult(
        satisfied=False,
        reason_code=reason,
        detail=detail,
        method_used=PRESENCE_METHOD_GEOFENCE,
        present_count=present,
        verified_member_ids=verified,
        window_satisfied=window_satisfied,
    )


def presence_status_payload(session, team, tower, challenge):
    """Player-facing presence status for a tower's challenge, or None.

    None when the effective requirement is the no-op default, so
    pre-change clients see no payload change. The present count is a
    point-in-time read of fresh pings (the viewer counts through their
    own ping stream here — there is no submission GPS yet).
    """
    resolved = resolve_presence(session, challenge, tower, team=team)
    if resolved['is_noop']:
        return None
    now = timezone.now()
    if resolved['method'] == PRESENCE_METHOD_PHOTO:
        present = []
    else:
        cutoff = _freshness_cutoff(session, now)
        latest = (
            _latest_pings(session, _member_user_ids(team), cutoff)
            if session.effective('location_tracking_enabled') else {}
        )
        present = [
            user_id for user_id, ping in latest.items()
            if _gis_inside(ping.point, tower, resolved['geofence_radius_meters'])
        ]
    return {
        'required_members': resolved['min_members'],
        'present_members': len(present),
        'present_member_ids': present,
        'method': resolved['method'],
        'photo_fallback_offered': resolved['method'] in (
            PRESENCE_METHOD_PHOTO, PRESENCE_METHOD_GEOFENCE_OR_PHOTO,
        ),
        'geofence_radius_meters': resolved['geofence_radius_meters'],
        'window_seconds': resolved['window_seconds'],
    }
