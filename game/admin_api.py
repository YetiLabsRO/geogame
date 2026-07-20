from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
    ROLE_REQUIREMENT_NONE,
    Challenge,
    PauseWindow,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from game.scoping import GameScopedViewSetMixin, SessionScopedViewSetMixin
from organize.models import (
    Game,
    GameRole,
    Session,
    Team,
    TeamGroup,
    TeamMembership,
    TeamRole,
)


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
        fields = (
            'id', 'game', 'text', 'tower', 'difficulty',
            'role_requirement_mode', 'required_roles', 'require_holders_present',
        )

    def validate(self, attrs):
        """team-roles config validation (task 2.3).

        `required_roles` must belong to the challenge's Game, and a
        non-NONE `role_requirement_mode` needs a non-empty role set.
        """
        instance = self.instance
        mode = attrs.get(
            'role_requirement_mode',
            instance.role_requirement_mode if instance else ROLE_REQUIREMENT_NONE,
        )
        if 'required_roles' in attrs:
            required = list(attrs['required_roles'])
        elif instance is not None:
            required = list(instance.required_roles.all())
        else:
            required = []
        game = attrs.get('game', instance.game if instance else None)

        if mode != ROLE_REQUIREMENT_NONE and not required:
            raise serializers.ValidationError(
                'A role requirement mode other than NONE needs at least one required role.',
            )
        foreign = [r.slug for r in required if game is None or r.game_id != game.id]
        if foreign:
            raise serializers.ValidationError(
                f'required_roles must belong to the challenge\'s Game: {", ".join(foreign)}.',
            )
        return attrs


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
    """Staff-only CRUD for Teams."""

    permission_classes = [IsAdminUser]
    queryset = Team.objects.all().order_by('name')
    serializer_class = AdminTeamSerializer
    session_scope_field = 'session'


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


# ---------------------------------------------------------------------------
# team-roles: role definitions + roster role assignment
# ---------------------------------------------------------------------------


class AdminGameRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GameRole
        fields = (
            'id', 'game', 'name', 'slug', 'description',
            'builtin_power', 'created_at',
        )
        read_only_fields = ('created_at',)


class AdminGameRoleViewSet(viewsets.ModelViewSet):
    """Staff CRUD for per-Game role definitions (team-roles capability).

    Like AdminSessionViewSet, not session-scoped: the Games page manages
    any Game's roles via ?game=<id>. A list without the param falls back
    to the caller's current Session's Game so scoped pages (e.g. the
    challenge editor) get the right roles with no extra plumbing.
    """

    permission_classes = [IsAdminUser]
    queryset = GameRole.objects.select_related('game').order_by('name')
    serializer_class = AdminGameRoleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        game_id = self.request.query_params.get('game')
        if game_id:
            return qs.filter(game_id=game_id)
        if getattr(self, 'action', None) == 'list':
            profile = getattr(self.request.user, 'profile', None)
            session = profile.current_session if profile else None
            if session is None:
                return qs.none()
            return qs.filter(game_id=session.game_id)
        return qs


class RoleSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = GameRole
        fields = ('id', 'slug', 'name', 'builtin_power')


class AdminTeamMembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.user.username', read_only=True)
    first_name = serializers.CharField(source='user.user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.user.last_name', read_only=True)
    roles = serializers.SerializerMethodField()

    class Meta:
        model = TeamMembership
        fields = (
            'id', 'team', 'user', 'username', 'first_name', 'last_name',
            'is_active', 'joined_at', 'roles',
        )

    def get_roles(self, membership):
        role_assignments = membership.roles.select_related('role').all()
        return RoleSummarySerializer(
            [tr.role for tr in role_assignments], many=True,
        ).data


class AdminTeamMembershipViewSet(SessionScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Staff roster view + role assign/unassign actions (team-roles).

    List supports ?team=<id> for a single team's roster. The assignable
    roles are strictly the membership's Game's roles — a role from
    another Game is rejected before it ever reaches the model layer.
    """

    permission_classes = [IsAdminUser]
    queryset = (
        TeamMembership.objects
        .select_related('user__user', 'team')
        .prefetch_related('roles__role')
        .order_by('team__name', 'user__user__username')
    )
    serializer_class = AdminTeamMembershipSerializer
    session_scope_field = 'team__session'

    def get_queryset(self):
        qs = super().get_queryset()
        team_id = self.request.query_params.get('team')
        if team_id:
            qs = qs.filter(team_id=team_id)
        return qs

    def _resolve_role(self, request, membership):
        role_id = request.data.get('role')
        if not role_id:
            return None, Response(
                {'detail': 'role is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        role = GameRole.objects.filter(
            pk=role_id, game_id=membership.game_id,
        ).first()
        if role is None:
            return None, Response(
                {'detail': 'Role not found on this membership\'s Game.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return role, None

    @action(detail=True, methods=['post'])
    def assign_role(self, request, pk=None):
        membership = self.get_object()
        role, error = self._resolve_role(request, membership)
        if error is not None:
            return error
        TeamRole.objects.get_or_create(
            membership=membership, role=role,
            defaults={'assigned_by': request.user},
        )
        return Response(self.get_serializer(membership).data)

    @action(detail=True, methods=['post'])
    def unassign_role(self, request, pk=None):
        membership = self.get_object()
        role, error = self._resolve_role(request, membership)
        if error is not None:
            return error
        TeamRole.objects.filter(membership=membership, role=role).delete()
        return Response(self.get_serializer(membership).data)


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
        """Pause every active Session of this Game in one call (§20.1)."""
        game = self.get_object()
        paused = []
        for session in game.sessions.filter(is_active=True):
            if PauseWindow.pause_session(session) is not None:
                paused.append(session.id)
        return Response({'paused_sessions': paused}, status=status.HTTP_200_OK)


class AdminSessionSerializer(serializers.ModelSerializer):
    game_slug = serializers.CharField(source='game.slug', read_only=True)
    game_name = serializers.CharField(source='game.name', read_only=True)
    is_paused = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = (
            'id', 'game', 'game_slug', 'game_name',
            'slug', 'name', 'start_time', 'end_time', 'is_active',
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
        read_only_fields = ('created_at', 'game_slug', 'game_name', 'is_paused')

    def get_is_paused(self, session):
        return PauseWindow.is_paused(session)


class AdminSessionViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Sessions.

    Not session-scoped for the same reason as AdminGameViewSet.
    Accepts ?game=<id> to filter to one Game's sessions for the UI.

    Deactivating a session (is_active True → False) closes every open
    TeamTowerOwnership / TeamZoneOwnership for teams in that session
    and locks in floating scores. Mirrors unassign_all but scoped to
    the session.
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
                qs = qs.filter(is_active=True)
            elif is_active.lower() in ('false', '0'):
                qs = qs.filter(is_active=False)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Open a PauseWindow on this Session (§20.1)."""
        session = self.get_object()
        window = PauseWindow.pause_session(session)
        if window is None:
            return Response(
                {'detail': 'Session is already paused.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(session).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Close the open PauseWindow, restoring ownerships if configured."""
        session = self.get_object()
        window = PauseWindow.resume_session(session)
        if window is None:
            return Response(
                {'detail': 'Session is not paused.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(session).data, status=status.HTTP_200_OK)

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
            'is_paused': PauseWindow.is_paused(session),
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

    @transaction.atomic
    def perform_update(self, serializer):
        # Read is_active straight from the DB so we're not sensitive to
        # when the serializer mutates its own instance.
        was_active = Session.objects.filter(pk=serializer.instance.pk).values_list(
            'is_active', flat=True,
        ).first()
        session = serializer.save()
        if was_active and not session.is_active:
            self._close_ownerships(session)

    def _close_ownerships(self, session):
        now = timezone.now()
        team_ids = list(session.teams.values_list('id', flat=True))

        TeamTowerOwnership.objects.filter(
            team_id__in=team_ids, timestamp_end__isnull=True,
        ).update(timestamp_end=now)

        # Zone ownerships lock in floating scores before they close.
        zone_ownerships = list(
            TeamZoneOwnership.objects
            .filter(team_id__in=team_ids, timestamp_end__isnull=True)
            .select_related('team', 'zone')
        )
        for zo in zone_ownerships:
            zo.timestamp_end = now
            zo.save()
            zo.team.update_score(zo.get_score())
