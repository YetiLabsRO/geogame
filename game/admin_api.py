import random
import secrets

from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
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
    Session,
    Team,
    TeamGroup,
    TeamMembership,
    UserProfile,
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
    captain_username = serializers.CharField(
        source='captain.username', read_only=True, default=None,
    )
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            'id', 'name', 'session', 'game',
            'group', 'color', 'description',
            # Team-formation fields: captain + per-team confirmation
            # override (null = inherit Game default) + untied join code.
            'captain', 'captain_username', 'team_join_confirmation',
            'join_code', 'member_count',
        )
        read_only_fields = ('join_code',)

    def get_member_count(self, team):
        return team.memberships.filter(is_active=True).count()


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
            # Team-formation knobs (defaults preserve staff-only rosters).
            'allow_player_team_creation', 'team_join_confirmation',
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
            # Team-formation override (null = inherit Game default).
            'allow_player_team_creation',
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

    # ---- Team shuffle / balanced build (team-formation, lower priority) ----

    def _unassigned_profiles(self, session):
        """Non-staff profiles pointed at this session without an active
        membership in its game — the pool the builders draw from."""
        return list(
            UserProfile.objects
            .filter(current_session=session, user__is_staff=False)
            .exclude(
                memberships__is_active=True,
                memberships__game=session.game,
            )
            .select_related('user')
        )

    def _build_teams(self, session, team_count):
        existing = set(session.teams.values_list('name', flat=True))
        teams = []
        index = 1
        while len(teams) < team_count:
            name = f'Team {index}'
            index += 1
            if name in existing:
                continue
            teams.append(Team.objects.create(
                name=name,
                session=session,
                color=f'#{secrets.randbelow(0xFFFFFF):06X}',
            ))
        return teams

    def _assignment_payload(self, teams):
        return {
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'members': [
                        m.user.user.get_username()
                        for m in t.memberships.filter(is_active=True).select_related('user__user')
                    ],
                }
                for t in teams
            ],
            'assigned': sum(
                t.memberships.filter(is_active=True).count() for t in teams
            ),
        }

    @action(detail=True, methods=['post'], url_path='shuffle-teams')
    @transaction.atomic
    def shuffle_teams(self, request, pk=None):
        """Randomly distribute the session's unassigned players into N
        new teams. Best-effort; the result stays editable before start."""
        session = self.get_object()
        try:
            team_count = int(request.data.get('team_count', 0))
        except (TypeError, ValueError):
            team_count = 0
        if team_count < 1:
            return Response(
                {'detail': 'team_count must be a positive integer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        players = self._unassigned_profiles(session)
        if not players:
            return Response(
                {'detail': 'No unassigned players in this session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        random.shuffle(players)
        teams = self._build_teams(session, team_count)
        for i, profile in enumerate(players):
            TeamMembership.objects.create(
                team=teams[i % team_count], user=profile, is_active=True,
            )
        return Response(self._assignment_payload(teams), status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='balance-teams')
    @transaction.atomic
    def balance_teams(self, request, pk=None):
        """Bucket unassigned players by profile attribute key(s) and deal
        them round-robin so each bucket spreads evenly across N teams."""
        session = self.get_object()
        try:
            team_count = int(request.data.get('team_count', 0))
        except (TypeError, ValueError):
            team_count = 0
        keys = request.data.get('attribute_keys') or []
        if isinstance(keys, str):
            keys = [keys]
        if team_count < 1 or not keys:
            return Response(
                {'detail': 'team_count (positive integer) and attribute_keys are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        players = self._unassigned_profiles(session)
        if not players:
            return Response(
                {'detail': 'No unassigned players in this session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        buckets = {}
        for profile in players:
            attrs = profile.attributes or {}
            bucket_key = tuple(str(attrs.get(k)) for k in keys)
            buckets.setdefault(bucket_key, []).append(profile)
        for members in buckets.values():
            random.shuffle(members)
        teams = self._build_teams(session, team_count)
        # Deal bucket by bucket (largest first), continuing the same
        # round-robin cursor so buckets spread evenly across teams.
        cursor = 0
        for _, members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            for profile in members:
                TeamMembership.objects.create(
                    team=teams[cursor % team_count], user=profile, is_active=True,
                )
                cursor += 1
        return Response(self._assignment_payload(teams), status=status.HTTP_200_OK)

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
