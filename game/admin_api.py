from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
    Challenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from game.scoping import GameScopedViewSetMixin, SessionScopedViewSetMixin
from organize.models import Game, IllegalTransition, Session, Team, TeamGroup


class RosterClosedError(APIException):
    """Team creation attempted while the session's roster is closed."""

    status_code = 409
    default_detail = 'Team rosters are closed in this session state.'
    default_code = 'roster_closed'


class AdminZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ('id', 'name', 'game', 'color', 'scoring_type')


class AdminTowerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tower
        fields = (
            'id', 'name', 'game', 'zone', 'category', 'is_active',
            'initial_bonus', 'rfid_code',
        )


class AdminTeamSerializer(serializers.ModelSerializer):
    # Read-only `game` derived from session.game for convenience in the
    # staff UI. Writes always go through `session`.
    game = serializers.IntegerField(source='session.game_id', read_only=True)

    class Meta:
        model = Team
        fields = (
            'id', 'name', 'session', 'game',
            'group', 'color', 'description',
        )


class AdminTeamGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamGroup
        fields = ('id', 'name', 'game', 'slug')


class AdminChallengeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Challenge
        fields = ('id', 'game', 'text', 'tower', 'difficulty')


class AdminZoneViewSet(GameScopedViewSetMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for Zones. Shape editing stays in Django admin."""

    permission_classes = [IsAdminUser]
    queryset = Zone.objects.all().order_by('name')
    serializer_class = AdminZoneSerializer
    game_scope_field = 'game'


class AdminTowerViewSet(GameScopedViewSetMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for Towers + activate/deactivate/unassign actions.

    Location (PointField) edits stay in Django admin. Everything else
    is reachable through this viewset.
    """

    permission_classes = [IsAdminUser]
    queryset = Tower.objects.all().order_by('name')
    serializer_class = AdminTowerSerializer
    game_scope_field = 'game'

    @action(detail=True, methods=['post'])
    def unassign(self, request, pk=None):
        tower = self.get_object()
        tower.unassign()
        return Response(self.get_serializer(tower).data)

    @action(detail=False, methods=['post'])
    def unassign_all(self, request):
        # Restrict the sweep to the staff user's current scope so one
        # game's admins can't accidentally close ownerships on another.
        towers = list(self.get_queryset().filter(is_active=True))
        for tower in towers:
            tower.unassign()
        return Response(
            {'unassigned': [t.id for t in towers]},
            status=status.HTTP_200_OK,
        )


class AdminTeamViewSet(SessionScopedViewSetMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for Teams.

    Team creation follows the session lifecycle: rosters form while the
    Session is OPEN_FOR_PARTICIPANTS (and, for now, while RUNNING or
    PAUSED); DRAFT and FINISHED reject creation with 409.
    """

    permission_classes = [IsAdminUser]
    queryset = Team.objects.all().order_by('name')
    serializer_class = AdminTeamSerializer
    session_scope_field = 'session'

    def perform_create(self, serializer):
        session = serializer.validated_data.get('session')
        if session is not None and not session.accepts_roster_changes():
            raise RosterClosedError(
                f'Teams cannot be created while the session is {session.state}. '
                'Open participation first.',
            )
        serializer.save()


class AdminTeamGroupList(GameScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Staff-only read access to TeamGroups (needed by the team edit form)."""

    permission_classes = [IsAdminUser]
    queryset = TeamGroup.objects.all().order_by('name')
    serializer_class = AdminTeamGroupSerializer
    game_scope_field = 'game'


class AdminChallengeViewSet(GameScopedViewSetMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for Challenges (tower-specific or generic)."""

    permission_classes = [IsAdminUser]
    queryset = Challenge.objects.all().order_by('difficulty', 'id')
    serializer_class = AdminChallengeSerializer
    game_scope_field = 'game'


class ResetScoresView(APIView):
    """Staff-only: zero out all Team.score and close every open ownership.

    Intended as a "start a fresh round" button. Distinct from
    unassign_all (which just closes current tower ownerships) in that
    this also resets the locked, cumulative Team.score to 0.
    """

    permission_classes = [IsAdminUser]

    @transaction.atomic
    def post(self, request):
        now = timezone.now()
        TeamTowerOwnership.objects.filter(
            timestamp_end__isnull=True,
        ).update(timestamp_end=now)
        TeamZoneOwnership.objects.filter(
            timestamp_end__isnull=True,
        ).update(timestamp_end=now)
        updated = Team.objects.update(score=0)
        return Response(
            {'teams_reset': updated},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Games + Sessions admin CRUD (T3.7)
# ---------------------------------------------------------------------------


class AdminGameSerializer(serializers.ModelSerializer):
    """Staff-writable Game payload.

    `base_point` reads as GeoJSON; writes accept {lat, lng} via
    write-only helper fields so clients don't need to know the PointField
    wire format.
    """

    base_point = serializers.SerializerMethodField(read_only=True)
    base_lat = serializers.FloatField(
        write_only=True, required=False, allow_null=True,
    )
    base_lng = serializers.FloatField(
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = Game
        fields = (
            'id', 'slug', 'name',
            'base_point', 'base_lat', 'base_lng',
            'base_zoom_level', 'is_active',
            'proximity_meters', 'cooloff_minutes', 'initial_bonus_default',
            # Phase 10 day-pausing knobs.
            'pause_freezes_floating_score',
            'pause_restores_ownerships_on_resume',
            'pause_rejects_submissions',
            # Phase 10 failure-consequence knobs.
            'fail_point_penalty', 'fail_cooloff_scaling',
            'fail_tower_lockout_minutes', 'fail_difficulty_rollback',
            'fail_counter_reset',
            'created_at',
        )
        read_only_fields = ('created_at',)

    def get_base_point(self, game):
        if game.base_point is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [game.base_point.x, game.base_point.y],
        }

    def _absorb_coords(self, validated):
        lat = validated.pop('base_lat', None)
        lng = validated.pop('base_lng', None)
        if lat is not None and lng is not None:
            validated['base_point'] = Point(lng, lat)

    def create(self, validated_data):
        self._absorb_coords(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._absorb_coords(validated_data)
        return super().update(instance, validated_data)


class AdminGameViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Games.

    Not session-scoped — admins need to list every Game to switch
    between them in the UI. Attaches `created_by` on create.
    """

    permission_classes = [IsAdminUser]
    queryset = Game.objects.all().order_by('name')
    serializer_class = AdminGameSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def pause_all(self, request, pk=None):
        """Pause every RUNNING Session of this Game in one call (§20.1).

        Routed through the same `pause` lifecycle transition as the
        per-session endpoint so every affected Session lands in PAUSED
        with its open PauseWindow (session-lifecycle invariant).
        """
        game = self.get_object()
        paused = []
        for session in game.sessions.filter(state=Session.RUNNING):
            session.transition('pause', actor=request.user)
            paused.append(session.id)
        return Response({'paused_sessions': paused}, status=status.HTTP_200_OK)


class AdminSessionSerializer(serializers.ModelSerializer):
    game_slug = serializers.CharField(source='game.slug', read_only=True)
    game_name = serializers.CharField(source='game.name', read_only=True)
    # Lifecycle: `state` changes only through the transition actions, and
    # `is_active` is a derived read-only property of it.
    is_active = serializers.BooleanField(read_only=True)
    is_paused = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = (
            'id', 'game', 'game_slug', 'game_name',
            'slug', 'name', 'start_time', 'end_time', 'scheduled_start',
            'state', 'allowed_transitions', 'is_active',
            'is_paused',
            # Phase 10 per-session overrides (null = inherit Game default).
            'pause_freezes_floating_score',
            'pause_restores_ownerships_on_resume',
            'pause_rejects_submissions',
            'fail_point_penalty', 'fail_cooloff_scaling',
            'fail_tower_lockout_minutes', 'fail_difficulty_rollback',
            'fail_counter_reset',
            'created_at',
        )
        read_only_fields = (
            'created_at', 'game_slug', 'game_name', 'state',
            'allowed_transitions', 'is_active', 'is_paused',
        )

    def get_is_paused(self, session):
        return session.is_paused()

    def get_allowed_transitions(self, session):
        return session.allowed_transitions


class AdminSessionViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD + lifecycle transitions for Sessions.

    Not session-scoped for the same reason as AdminGameViewSet.
    Accepts ?game=<id> to filter to one Game's sessions for the UI;
    ?is_active=true|false filters on the derived active-state set, and
    ?state=<STATE> on the exact lifecycle state.

    The lifecycle `state` is never writable through create/update — it
    changes only through the transition actions below, each mapping one
    edge of the Session.TRANSITIONS table; illegal transitions are 409.
    """

    permission_classes = [IsAdminUser]
    queryset = Session.objects.select_related('game').order_by('-start_time')
    serializer_class = AdminSessionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        game_id = self.request.query_params.get('game')
        if game_id:
            qs = qs.filter(game_id=game_id)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            if is_active.lower() in ('true', '1'):
                qs = qs.filter(state__in=Session.ACTIVE_STATES)
            elif is_active.lower() in ('false', '0'):
                qs = qs.exclude(state__in=Session.ACTIVE_STATES)
        state = self.request.query_params.get('state')
        if state:
            qs = qs.filter(state=state.upper())
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ---- Lifecycle transition actions (session-lifecycle) ------------------

    def _transition(self, request, action_name):
        """Drive one lifecycle action; 409 on illegal transitions."""
        session = self.get_object()
        override = bool(request.data.get('override', False))
        try:
            session.transition(
                action_name, actor=request.user, override=override,
            )
        except IllegalTransition as exc:
            payload = {'detail': str(exc)}
            if exc.requires_override:
                payload['requires_override'] = True
            return Response(payload, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(session).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def open_participation(self, request, pk=None):
        """DRAFT → OPEN_FOR_PARTICIPANTS: open the roster window."""
        return self._transition(request, 'open_participation')

    @action(detail=True, methods=['post'])
    def close_participation(self, request, pk=None):
        """OPEN_FOR_PARTICIPANTS → DRAFT: re-close the roster window."""
        return self._transition(request, 'close_participation')

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """OPEN_FOR_PARTICIPANTS → RUNNING: start the Session clock."""
        return self._transition(request, 'start')

    @action(detail=True, methods=['post'])
    def finish(self, request, pk=None):
        """RUNNING|PAUSED → FINISHED: close ownerships, keep history."""
        return self._transition(request, 'finish')

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """RUNNING → PAUSED: open a PauseWindow atomically (§20.1)."""
        return self._transition(request, 'pause')

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """PAUSED → RUNNING: close the newest open PauseWindow."""
        return self._transition(request, 'resume')

    @action(detail=True, methods=['get'])
    def pause_history(self, request, pk=None):
        """Current pause state + this session's PauseWindow history (§20 UI)."""
        session = self.get_object()
        windows = [
            {
                'id': w.id,
                'started_at': w.started_at,
                'ended_at': w.ended_at,
                'restore_on_resume': w.restore_on_resume,
            }
            for w in session.pause_windows.order_by('-started_at')
        ]
        return Response({
            'is_paused': session.is_paused(),
            'windows': windows,
        })

    @action(detail=True, methods=['get'])
    def fail_counters(self, request, pk=None):
        """Current lockouts + consecutive-fail counts for the session (§21 UI)."""
        session = self.get_object()
        team_ids = list(session.teams.values_list('id', flat=True))
        now = timezone.now()
        counters = (
            TeamTowerFailCounter.objects
            .filter(team_id__in=team_ids, consecutive_fails__gt=0)
            .select_related('team', 'tower')
            .order_by('-consecutive_fails')
        )
        data = [
            {
                'team_id': c.team_id,
                'team_name': c.team.name,
                'team_color': c.team.color,
                'tower_id': c.tower_id,
                'tower_name': c.tower.name,
                'consecutive_fails': c.consecutive_fails,
                'locked_until': c.locked_until,
                'is_locked': bool(c.locked_until and c.locked_until > now),
            }
            for c in counters
        ]
        return Response(data)

