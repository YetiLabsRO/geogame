"""Discovery APIs (discovery-tracking capability).

- `POST /api/discovery/ping/`   — self-contained position fallback:
  report a position, run the discovery evaluation, get back the towers
  this position newly revealed. Works with location tracking off, so
  discovery never depends on the live-location capability being enabled.
- `GET /api/discovery/towers/`  — the caller team's discovered towers
  for the current Session.
- `POST /api/staff/discovery/reveal/` — staff override: reveal a tower
  to a team directly (`method=STAFF`), independent of position.

The live-location ping stream funnels through the same
`evaluate_discovery` routine (see `game.location_api.LocationPingView`),
so both sources create discoveries identically.
"""
from django.contrib.gis.geos import Point
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.discovery import evaluate_discovery, staff_reveal
from game.location_api import _active_team
from game.models import Tower, TowerDiscovery
from game.scoping import _current_session
from organize.models import Team


def _no_session_response():
    return Response(
        {'detail': 'You are not in any session.'},
        status=status.HTTP_404_NOT_FOUND,
    )


def _discovery_payload(discovery):
    tower = discovery.tower
    return {
        'tower_id': tower.id,
        'tower_name': tower.name,
        'location': {
            'type': 'Point',
            'coordinates': [tower.location.x, tower.location.y],
        },
        'method': discovery.method,
        'discovered_at': discovery.discovered_at,
    }


class DiscoveryPingView(APIView):
    """Report one position; evaluate and return the newly revealed towers."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = _current_session(request)
        if session is None:
            return _no_session_response()
        team = _active_team(request.user, session)
        if team is None:
            return Response(
                {'detail': 'You are not a member of any team in this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            point = Point(
                float(request.data.get('lng')),
                float(request.data.get('lat')),
                srid=4326,
            )
        except (TypeError, ValueError):
            return Response(
                {'detail': 'lat and lng are required numbers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_rows = evaluate_discovery(session, team, point, user=request.user)
        return Response({
            'session': session.id,
            'team': team.id,
            'newly_revealed': [_discovery_payload(d) for d in new_rows],
        })


class DiscoveredTowersView(APIView):
    """The caller team's discovered towers in the current Session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        if session is None:
            return _no_session_response()
        team = _active_team(request.user, session)
        if team is None:
            return Response(
                {'detail': 'You are not a member of any team in this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        discoveries = (
            TowerDiscovery.objects
            .filter(session=session, team=team)
            .select_related('tower')
            .order_by('discovered_at')
        )
        return Response({
            'session': session.id,
            'team': team.id,
            'towers': [_discovery_payload(d) for d in discoveries],
        })


class StaffRevealView(APIView):
    """Staff override: reveal a tower to a team (`method=STAFF`)."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        team = Team.objects.filter(pk=request.data.get('team')).select_related('session').first()
        tower = Tower.objects.filter(pk=request.data.get('tower')).first()
        if team is None or tower is None:
            return Response(
                {'detail': 'team and tower must be valid ids.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not team.session.towers().filter(pk=tower.pk).exists():
            return Response(
                {'detail': 'That tower is not part of the team\'s game.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        discovery = staff_reveal(team, tower, user=request.user)
        return Response(
            _discovery_payload(discovery) | {'team': team.id, 'method': discovery.method},
            status=status.HTTP_201_CREATED,
        )
