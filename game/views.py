import secrets
import uuid

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.db import OperationalError, connection, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from game.models import Challenge, TeamTowerChallenge, Tower, Zone
from game.scoping import (
    GameGeometryScopedViewSetMixin,
    GameScopedViewSetMixin,
    SessionScopedViewSetMixin,
    _current_session,
)
from game.serializers import (
    ChallengeSerializer,
    TeamSerializer,
    TeamTowerChallengeSerializer,
    TowerSerializer,
    ZoneSerializer,
)
from game.trail import (
    on_submission_confirmed,
    on_submission_created,
    revealed_tower_ids,
)
from organize.models import (
    MODE_TRAIL,
    Team,
    TeamGroup,
    TeamMembership,
    effective_allow_player_team_creation,
    effective_mode,
)


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
        # mode-trail-discovery: on a TRAIL session, mask trail points the
        # caller's party has not revealed yet (per-party map masking —
        # see game.trail.revealed_tower_ids).
        session = _current_session(self.request)
        if session is not None:
            profile = self.request.user.profile
            membership = profile.memberships.filter(
                is_active=True, team__session=session,
            ).select_related('team').first()
            revealed = revealed_tower_ids(
                session,
                team=membership.team if membership else None,
                profile=profile,
            )
            if revealed is not None:
                queryset = queryset.filter(pk__in=revealed)
        if self.request.query_params.get("lat") and self.request.query_params.get("lng"):
            lat = float(self.request.query_params.get("lat"))
            lng = float(self.request.query_params.get("lng"))
            point = Point(lng, lat)
            radius = min(float(self.request.query_params.get("accuracy", 100.)), 50.)

            return queryset.filter(location__distance_lt=(point, Distance(m=radius)))
        return queryset


def _random_team_color():
    return f'#{secrets.randbelow(0xFFFFFF):06X}'


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

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Create a team in the caller's current Session.

        Staff may always create teams. A player may create one only when
        the effective `allow_player_team_creation` toggle is enabled for
        their current Session; the creator becomes the captain and first
        member (see the team-formation capability).
        """
        user = request.user
        session = user.profile.current_session
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        is_player_create = not user.is_staff
        if is_player_create:
            if not effective_allow_player_team_creation(session):
                return Response(
                    {'detail': 'Player team creation is not enabled for this session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if Team.objects.filter(session=session, captain=user).exists():
                return Response(
                    {'detail': 'You have already created a team in this session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            membership = (
                TeamMembership.objects
                .filter(user=user.profile, is_active=True, game=session.game)
                .select_related('team')
                .first()
            )
            if membership is not None:
                return Response(
                    {
                        'detail': (
                            f'You are already on team "{membership.team.name}" in '
                            f'"{session.game.name}". Leave that team before '
                            'creating another in the same game.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        data = request.data.copy()
        if not data.get('color'):
            data['color'] = _random_team_color()
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        group = serializer.validated_data.get('group')
        if group is not None and group.game_id != session.game_id:
            return Response(
                {'detail': 'That team group belongs to a different game.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra = {'session': session}
        if is_player_create:
            # The creator becomes captain and gets an untied join code to
            # share right away. Role-based invite powers are a future
            # change (team-roles-as-mechanics).
            extra['captain'] = user
            extra['join_code'] = uuid.uuid4()
        team = serializer.save(**extra)
        if is_player_create:
            TeamMembership.objects.create(
                team=team, user=user.profile, is_active=True,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers,
        )


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
        if effective_mode(ttc.team.session) == MODE_TRAIL:
            # mode-trail-discovery: geofenced arrival marks the step
            # ARRIVED; a confirmed gate unlocks it. Domination capture
            # (tower ownership + bonus) stays inert in TRAIL mode.
            on_submission_created(ttc)
            if ttc.outcome == TeamTowerChallenge.CONFIRMED:
                on_submission_confirmed(ttc)
        elif ttc.outcome == TeamTowerChallenge.CONFIRMED:
            ttc.tower.assign_to_team(ttc.team)


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok"})
