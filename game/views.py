from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.db import OperationalError, connection
from django.db.models import Count, Q
from django.http import JsonResponse
from rest_framework import permissions, viewsets

from game.models import Challenge, TeamTowerChallenge, Tower, Zone
from game.scoping import (
    GameGeometryScopedViewSetMixin,
    GameScopedViewSetMixin,
    SessionScopedViewSetMixin,
)
from game.serializers import (
    ChallengeSerializer,
    TeamSerializer,
    TeamTowerChallengeSerializer,
    TowerSerializer,
    ZoneSerializer,
)
from organize.models import Team, TeamGroup


class ZoneViewSet(GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'zones'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.annotate(
            num_towers=Count('tower', Q(tower__is_active=True)),
        ).filter(num_towers__gte=1)

    def get_serializer_context(self):
        context = super(ZoneViewSet, self).get_serializer_context()
        group_id = self.request.query_params.get('group')
        group_slug = self.request.query_params.get('group_slug')
        if not group_id and group_slug:
            group = TeamGroup.objects.filter(slug=group_slug).first()
            group_id = group.id if group else 0
        context['group'] = group_id or 0
        return context


class TowerViewSet(GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Tower.objects.exclude(is_active=False).exclude(category=Tower.CATEGORY_RFID)
    serializer_class = TowerSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'towers'

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("lat") and self.request.query_params.get("lng"):
            lat = float(self.request.query_params.get("lat"))
            lng = float(self.request.query_params.get("lng"))
            point = Point(lng, lat)
            radius = min(float(self.request.query_params.get("accuracy", 100.)), 50.)

            return queryset.filter(location__distance_lt=(point, Distance(m=radius)))
        return queryset


class TeamViewSet(SessionScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
    session_scope_field = 'session'

    def get_queryset(self):
        qs = super().get_queryset()
        category = int(self.request.query_params.get("category", 0))
        if category:
            qs = qs.filter(category=category)
        return qs

    def get_serializer_context(self):
        context = super(TeamViewSet, self).get_serializer_context()
        context['category'] = self.request.query_params.get('category', 0)
        return context


class ChallengeViewSet(GameScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Challenge.objects.all()
    serializer_class = ChallengeSerializer
    permission_classes = [permissions.IsAuthenticated]
    game_scope_field = 'game'


class TeamTowerChallengeViewSet(SessionScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = TeamTowerChallenge.objects.all()
    serializer_class = TeamTowerChallengeSerializer
    permission_classes = [permissions.IsAuthenticated]
    session_scope_field = 'team__session'

    def perform_create(self, serializer):
        ttc = serializer.save()
        if ttc.outcome == TeamTowerChallenge.CONFIRMED:
            ttc.tower.assign_to_team(ttc.team)


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok"})
