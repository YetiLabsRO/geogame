import secrets
import uuid

from django.contrib.gis.db.models.functions import Distance as DistanceFunc
from django.contrib.gis.geos import Point
from django.db import OperationalError, connection, transaction
from django.db.models import Count, F, FloatField, Q, Value
from django.db.models.functions import Cast, Coalesce, Least
from django.http import JsonResponse
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from game.discovery import evaluate_discovery, visible_towers, visible_zone_ids
from game.location_api import _active_team
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
from organize.models import (
    Team,
    TeamGroup,
    TeamMembership,
    effective_allow_player_team_creation,
)


class TeamVisibilityMixin:
    """Caller-team resolution + ownership-reveal context (tower-visibility).

    Staff and team-less callers are omniscient: the visibility filter is
    bypassed and ownership colouring stays complete. Player callers are
    filtered to their team's visible geometry, and the serializers are
    handed the context needed to conceal other teams' control when the
    effective `reveal_other_teams_ownership` is False.
    """

    def _visibility_context(self):
        session = _current_session(self.request)
        team = None
        if session is not None and not self.request.user.is_staff:
            team = _active_team(self.request.user, session)
        reveal_others = True
        if session is not None and team is not None:
            reveal_others = bool(session.effective('reveal_other_teams_ownership'))
        return session, team, reveal_others

    def get_serializer_context(self):
        context = super().get_serializer_context()
        session, team, reveal_others = self._visibility_context()
        context['team'] = team
        context['reveal_others'] = reveal_others
        return context


class ZoneViewSet(TeamVisibilityMixin, GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'zones'

    def get_queryset(self):
        qs = super().get_queryset()
        # Member towers are the many-to-many `towers` reverse
        # (tower-zone-topology) — not the removed single FK.
        qs = qs.annotate(
            num_towers=Count('towers', filter=Q(towers__is_active=True)),
        ).filter(num_towers__gte=1)
        # tower-visibility: hide a zone whose only towers are
        # undiscovered FOG_REVEAL towers. Staff/team-less callers bypass.
        session, team, _reveal = self._visibility_context()
        if session is not None and team is not None:
            qs = qs.filter(pk__in=visible_zone_ids(session, team))
        return qs

    def get_serializer_context(self):
        context = super(ZoneViewSet, self).get_serializer_context()
        group_id = self.request.query_params.get('group')
        group_slug = self.request.query_params.get('group_slug')
        if not group_id and group_slug:
            group = TeamGroup.objects.filter(slug=group_slug).first()
            group_id = group.id if group else 0
        context['group'] = group_id or 0
        return context


class TowerViewSet(TeamVisibilityMixin, GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Tower.objects.exclude(is_active=False).exclude(category=Tower.CATEGORY_RFID)
    serializer_class = TowerSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'towers'

    def get_queryset(self):
        queryset = super().get_queryset()
        session, team, _reveal = self._visibility_context()
        if session is not None and team is not None:
            lat = self.request.query_params.get('lat')
            lng = self.request.query_params.get('lng')
            if lat and lng:
                # A reported position drives discovery evaluation too, so
                # walking near a HIDDEN tower pops it up on the next fetch
                # (discovery-tracking capability).
                evaluate_discovery(
                    session, team,
                    Point(float(lng), float(lat), srid=4326),
                    user=self.request.user,
                )
            # Team-visibility filter at the queryset level: undiscovered
            # HIDDEN/FOG_REVEAL geometry never reaches the client.
            queryset = queryset.filter(
                pk__in=visible_towers(session, team).values('pk'),
            )
        if self.request.query_params.get("lat") and self.request.query_params.get("lng"):
            lat = float(self.request.query_params.get("lat"))
            lng = float(self.request.query_params.get("lng"))
            point = Point(lng, lat, srid=4326)
            accuracy = float(self.request.query_params.get("accuracy", 100.))

            # Effective per-tower radius (zone-conquest-and-scoring-config):
            # the tower's own proximity_meters when set, else the Game's
            # game-wide default — each capped by the reported GPS accuracy,
            # preserving the historical `min(accuracy, game default)` shape.
            session = _current_session(self.request)
            default_radius = float(
                session.game.proximity_meters if session is not None else 50,
            )
            return queryset.annotate(
                _distance=DistanceFunc('location', point),
                _radius=Least(
                    Coalesce(
                        Cast('proximity_meters', FloatField()),
                        Value(default_radius),
                    ),
                    Value(accuracy),
                    output_field=FloatField(),
                ),
            ).filter(_distance__lt=F('_radius'))
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
