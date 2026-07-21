"""Live-location APIs (live-location capability).

Transport + consent gate for streamed player positions:

- `POST /api/location/ping/`     — ingest a consented position sample
- `GET  /api/location/live/`     — latest visible position per player
- `GET/POST/DELETE /api/location/consent/` — consent status / grant / withdraw
- `GET /api/staff/sessions/{id}/location-history/` — after-game replay feed

All of it is a no-op unless the Session's effective
`location_tracking_enabled` is true (default false). Visibility of the
live feed is bounded by the effective `location_visibility`
(NONE/OWN_TEAM/EVERYONE); staff always see all consenting players.
"""
from django.contrib.gis.geos import Point
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import LocationConsent, LocationPing
from organize.models import (
    LOCATION_VISIBILITY_EVERYONE,
    LOCATION_VISIBILITY_NONE,
    TEAMMATE_VISIBILITY_SELECT_COUNT,
    Session,
    TeamMembership,
)


class LocationTrackingDisabledError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Location tracking is not enabled for this session.'
    default_code = 'location_tracking_disabled'


class LocationConsentRequiredError(APIException):
    """403 with an actionable pointer at the consent step."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = (
        'This session tracks live location; you must agree to its location '
        'rules first. Review and accept them at the consent step '
        '(POST /api/location/consent/).'
    )
    default_code = 'location_consent_required'


def _current_session(request):
    profile = getattr(request.user, 'profile', None)
    return profile.current_session if profile else None


def tracking_enabled(session):
    """Effective location_tracking_enabled for `session` (default False)."""
    if session is None:
        return False
    return bool(session.effective('location_tracking_enabled'))


def location_consent_blocker(user, session):
    """Return an APIException for the consent gate, or None when clear.

    The gate applies only when the session's effective config has
    tracking enabled AND the user holds no standing consent. Callers
    (submission serializer, ping ingestion) raise the returned error.
    """
    if not tracking_enabled(session):
        return None
    if getattr(user, 'is_staff', False):
        return None
    if LocationConsent.standing_for(user, session) is None:
        return LocationConsentRequiredError()
    return None


def _active_team(user, session):
    """The user's active team in `session`, or None."""
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    membership = (
        TeamMembership.objects
        .filter(user=profile, is_active=True, team__session=session)
        .select_related('team')
        .first()
    )
    return membership.team if membership else None


def _consenting_user_ids(session):
    return LocationConsent.objects.filter(
        session=session, withdrawn_at__isnull=True,
    ).values_list('user_id', flat=True)


def _ping_payload(ping):
    return {
        'user_id': ping.user_id,
        'username': ping.user.username,
        'team_id': ping.team_id,
        'team_name': ping.team.name if ping.team else None,
        'team_color': ping.team.color if ping.team else None,
        'lat': ping.point.y,
        'lng': ping.point.x,
        'accuracy': ping.accuracy,
        'recorded_at': ping.recorded_at,
        'received_at': ping.received_at,
    }


class LocationConsentView(APIView):
    """Consent status / grant / withdrawal for the current Session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        consent = LocationConsent.standing_for(request.user, session)
        return Response({
            'session': session.id,
            'tracking_enabled': tracking_enabled(session),
            'consent_required': tracking_enabled(session),
            'has_consent': consent is not None,
            'agreed_at': consent.agreed_at if consent else None,
            'consent_text': session.effective('location_consent_text') or '',
            'ping_interval_seconds': session.effective('location_ping_interval_seconds'),
        })

    def post(self, request):
        session = _current_session(request)
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not tracking_enabled(session):
            raise LocationTrackingDisabledError()
        consent = LocationConsent.grant(request.user, session)
        return Response(
            {
                'session': session.id,
                'has_consent': True,
                'agreed_at': consent.agreed_at,
                'consent_text': consent.consent_text,
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        """Withdraw consent: stop streaming and purge this user's pings."""
        session = _current_session(request)
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        consent = LocationConsent.standing_for(request.user, session)
        if consent is not None:
            consent.withdraw()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LocationPingView(APIView):
    """Ingest one position sample from a consented player."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = _current_session(request)
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not tracking_enabled(session):
            raise LocationTrackingDisabledError()
        # Everyone (staff included) needs standing consent before their
        # own position is stored — staff bypass only the *play* gate.
        if LocationConsent.standing_for(request.user, session) is None:
            raise LocationConsentRequiredError()

        lat, lng = request.data.get('lat'), request.data.get('lng')
        try:
            point = Point(float(lng), float(lat))
        except (TypeError, ValueError):
            return Response(
                {'detail': 'lat and lng are required numbers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        accuracy = request.data.get('accuracy')
        try:
            accuracy = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            accuracy = None
        recorded_at = None
        if request.data.get('recorded_at'):
            recorded_at = parse_datetime(str(request.data['recorded_at']))
        if recorded_at is None:
            recorded_at = timezone.now()

        team = _active_team(request.user, session)
        ping = LocationPing.objects.create(
            user=request.user,
            session=session,
            team=team,
            point=point,
            accuracy=accuracy,
            recorded_at=recorded_at,
        )
        return Response(
            {
                'id': ping.id,
                'recorded_at': ping.recorded_at,
                'received_at': ping.received_at,
                'ping_interval_seconds': session.effective('location_ping_interval_seconds'),
            },
            status=status.HTTP_201_CREATED,
        )


def visible_live_pings(session, user):
    """Latest ping per consenting player, filtered for `user`'s eyes.

    Staff always see every consenting player. Players pass two layers:

    1. `location_visibility` (live-location) — the authoritative coarse
       gate. NONE yields nothing (kill switch), OWN_TEAM bounds the
       feed to the caller's active team, EVERYONE allows the whole
       session.
    2. `teammate_visibility_mode` (presence-rules) — refines *within*
       what layer 1 allows. SELECT_COUNT keeps only the
       `teammate_visibility_count` players nearest the caller's own
       latest position (plus the caller). OWN_TEAM — the default — and
       EVERYONE add no further restriction: the OWN_TEAM/EVERYONE
       split is already decided by layer 1, whose own default is
       own-team, so unconfigured games behave identically.

    Precedence: the more restrictive layer wins — teammate visibility
    can only narrow (nearest-N); it never widens `location_visibility`
    (an EVERYONE teammate mode does not leak positions past an
    OWN_TEAM or NONE location gate).
    """
    latest = (
        LocationPing.objects
        .latest_per_user(session)
        .filter(user_id__in=_consenting_user_ids(session))
        .select_related('user', 'team')
    )
    if user.is_staff:
        return list(latest)

    visibility = session.effective('location_visibility')
    if visibility == LOCATION_VISIBILITY_NONE:
        return []
    caller_team = _active_team(user, session)
    if visibility != LOCATION_VISIBILITY_EVERYONE:
        # OWN_TEAM (the default) — nothing without a team.
        if caller_team is None:
            return []
        latest = latest.filter(team=caller_team)

    # presence-rules refinement (layer 2): only SELECT_COUNT narrows
    # further; OWN_TEAM/EVERYONE defer to the layer-1 decision above.
    teammate_mode = session.effective('teammate_visibility_mode')
    if teammate_mode == TEAMMATE_VISIBILITY_SELECT_COUNT:
        return _nearest_pings(list(latest), user, session)
    return list(latest)


def _nearest_pings(pings, user, session):
    """SELECT_COUNT: the caller plus their N nearest players.

    Distance is measured from the caller's own latest ping; without one
    the order falls back to recency (the caller cannot be localized).
    """
    count = session.effective('teammate_visibility_count') or 0
    own = [p for p in pings if p.user_id == user.id]
    others = [p for p in pings if p.user_id != user.id]
    anchor = own[0] if own else None
    if anchor is not None:
        others.sort(key=lambda p: anchor.point.distance(p.point))
    else:
        others.sort(key=lambda p: p.recorded_at, reverse=True)
    return own + others[:count]


class LocationLiveView(APIView):
    """Latest visible position per player for the caller's Session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # presence-rules owns the teammate-visibility config; the live
        # plotting (this feed) is its consumer — expose the resolved
        # values so clients can label/limit their overlay accordingly.
        teammate_visibility = {
            'mode': session.effective('teammate_visibility_mode'),
            'count': session.effective('teammate_visibility_count'),
        }
        if not tracking_enabled(session):
            return Response({
                'session': session.id,
                'tracking_enabled': False,
                'visibility': session.effective('location_visibility'),
                'teammate_visibility': teammate_visibility,
                'players': [],
            })
        pings = visible_live_pings(session, request.user)
        return Response({
            'session': session.id,
            'tracking_enabled': True,
            'visibility': session.effective('location_visibility'),
            'teammate_visibility': teammate_visibility,
            'players': [_ping_payload(p) for p in pings],
        })


class StaffLocationHistoryView(APIView):
    """Staff-only LocationPing series for a Session (after-game replay).

    Filterable by `?user=<id>`, `?team=<id>`, and a `?from=`/`?to=`
    ISO-datetime window. The series survives Session finish/deactivation
    until the retention window purges it.
    """

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        pings = (
            LocationPing.objects
            .filter(session=session)
            .select_related('user', 'team')
            .order_by('user_id', 'recorded_at')
        )
        user_id = request.query_params.get('user')
        if user_id:
            pings = pings.filter(user_id=user_id)
        team_id = request.query_params.get('team')
        if team_id:
            pings = pings.filter(team_id=team_id)
        window_from = request.query_params.get('from')
        if window_from:
            parsed = parse_datetime(window_from)
            if parsed is not None:
                pings = pings.filter(recorded_at__gte=parsed)
        window_to = request.query_params.get('to')
        if window_to:
            parsed = parse_datetime(window_to)
            if parsed is not None:
                pings = pings.filter(recorded_at__lte=parsed)
        return Response({
            'session': session.id,
            'retention_days': session.effective('location_retention_days'),
            'pings': [_ping_payload(p) for p in pings],
        })
