from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
    Challenge,
    Collection,
    PauseWindow,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from game.scoping import (
    GameScopedViewSetMixin,
    SessionScopedViewSetMixin,
    _current_session,
)
from organize.models import Game, Session, Team, TeamGroup


class GeometryUsageMixin(serializers.Serializer):
    """Usage reporting for repository assets (spec: usage visibility).

    Shows which Collections contain the Tower/Zone and which Games
    reference it through those collections, so edits/deletes are made
    with awareness of shared usage.
    """

    collections = serializers.SerializerMethodField()
    games = serializers.SerializerMethodField()

    def get_collections(self, obj):
        return [
            {'id': c.id, 'name': c.name}
            for c in obj.collections.all().order_by('name')
        ]

    def get_games(self, obj):
        return [
            {'id': g.id, 'name': g.name}
            for g in Game.objects.filter(collections__in=obj.collections.all())
            .distinct().order_by('name')
        ]


class AdminZoneSerializer(GeometryUsageMixin, serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ('id', 'name', 'color', 'scoring_type', 'collections', 'games')


class AdminTowerSerializer(GeometryUsageMixin, serializers.ModelSerializer):
    class Meta:
        model = Tower
        fields = (
            'id', 'name', 'zone', 'category', 'is_active',
            'initial_bonus', 'rfid_code', 'collections', 'games',
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


class CollectionFilterMixin:
    """Repository scoping for staff Tower/Zone endpoints.

    The whole repository is listed by default; `?collection=<id>`
    narrows to one Collection's members.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        collection_id = self.request.query_params.get('collection')
        if collection_id:
            qs = qs.filter(collections=collection_id)
        return qs


class AdminZoneViewSet(CollectionFilterMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for repository Zones. Shape editing stays in Django admin."""

    permission_classes = [IsAdminUser]
    queryset = Zone.objects.all().order_by('name')
    serializer_class = AdminZoneSerializer


class AdminTowerViewSet(CollectionFilterMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for repository Towers + activate/deactivate/unassign actions.

    Location (PointField) edits stay in Django admin. Everything else
    is reachable through this viewset.
    """

    permission_classes = [IsAdminUser]
    queryset = Tower.objects.all().order_by('name')
    serializer_class = AdminTowerSerializer

    @action(detail=True, methods=['post'])
    def unassign(self, request, pk=None):
        tower = self.get_object()
        tower.unassign()
        return Response(self.get_serializer(tower).data)

    @action(detail=False, methods=['post'])
    def unassign_all(self, request):
        # Restrict the sweep to the staff user's current session's Game
        # so one game's admins can't accidentally close ownerships on
        # another game sharing the same repository towers.
        session = _current_session(request)
        if session is None:
            towers = []
        else:
            towers = list(session.game.towers().filter(is_active=True))
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
    """Staff-only CRUD for Challenges (tower-specific or generic).

    The challenge bank is template data: mutating it requires template
    edit rights on the owning Game (creator / CREATOR collaborator).
    A runner personalises their own clone instead.
    """

    permission_classes = [IsAdminUser]
    queryset = Challenge.objects.all().order_by('difficulty', 'id')
    serializer_class = AdminChallengeSerializer
    game_scope_field = 'game'

    def _require_edit(self, game):
        if game is not None and not game.can_edit(self.request.user):
            raise PermissionDenied(
                'Only the game creator may modify its challenge bank. '
                'Clone the game to personalise it.',
            )

    def perform_create(self, serializer):
        self._require_edit(serializer.validated_data.get('game'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_edit(serializer.instance.game)
        self._require_edit(serializer.validated_data.get('game'))
        serializer.save()

    def perform_destroy(self, instance):
        self._require_edit(instance.game)
        instance.delete()


# ---------------------------------------------------------------------------
# Collections (points repository)
# ---------------------------------------------------------------------------


class AdminCollectionSerializer(serializers.ModelSerializer):
    """Staff payload for Collections.

    `towers` / `zones` list member PKs (read-only here — membership is
    curated through the dedicated add/remove actions). `games` reports
    which Games link this collection.
    """

    towers = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    zones = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    games = serializers.SerializerMethodField()
    slug = serializers.SlugField(required=False, allow_blank=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True, default=None,
    )

    class Meta:
        model = Collection
        fields = (
            'id', 'name', 'slug', 'description',
            'created_by', 'created_by_username', 'created_at',
            'towers', 'zones', 'games',
        )
        read_only_fields = ('created_by', 'created_at')

    def get_games(self, collection):
        return [
            {'id': g.id, 'name': g.name}
            for g in collection.games.all().order_by('name')
        ]

    def validate(self, attrs):
        # Auto-generate a unique slug from the name when absent.
        if not attrs.get('slug') and self.instance is None:
            base = slugify(attrs.get('name', ''))[:70] or 'collection'
            slug, counter = base, 2
            while Collection.objects.filter(slug=slug).exists():
                slug = f'{base}-{counter}'
                counter += 1
            attrs['slug'] = slug
        return attrs


class AdminCollectionViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Collections + tower/zone membership curation.

    Membership actions take `{"tower_ids": [...]}` / `{"zone_ids": [...]}`.
    Removing members never deletes the underlying repository rows.
    """

    permission_classes = [IsAdminUser]
    queryset = Collection.objects.all().order_by('name')
    serializer_class = AdminCollectionSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def _members(self, request, key, model):
        ids = request.data.get(key)
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise serializers.ValidationError({key: 'Expected a list of integer ids.'})
        found = list(model.objects.filter(pk__in=ids))
        if len(found) != len(set(ids)):
            raise serializers.ValidationError({key: 'One or more ids do not exist.'})
        return found

    @action(detail=True, methods=['post'], url_path='add-towers')
    def add_towers(self, request, pk=None):
        collection = self.get_object()
        collection.towers.add(*self._members(request, 'tower_ids', Tower))
        return Response(self.get_serializer(collection).data)

    @action(detail=True, methods=['post'], url_path='remove-towers')
    def remove_towers(self, request, pk=None):
        collection = self.get_object()
        collection.towers.remove(*self._members(request, 'tower_ids', Tower))
        return Response(self.get_serializer(collection).data)

    @action(detail=True, methods=['post'], url_path='add-zones')
    def add_zones(self, request, pk=None):
        collection = self.get_object()
        collection.zones.add(*self._members(request, 'zone_ids', Zone))
        return Response(self.get_serializer(collection).data)

    @action(detail=True, methods=['post'], url_path='remove-zones')
    def remove_zones(self, request, pk=None):
        collection = self.get_object()
        collection.zones.remove(*self._members(request, 'zone_ids', Zone))
        return Response(self.get_serializer(collection).data)


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
    collections = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Collection.objects.all(), required=False,
    )
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True, default=None,
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
            # Repository / roles / cloning.
            'collections', 'created_by', 'created_by_username', 'cloned_from',
            'created_at',
        )
        read_only_fields = ('created_at', 'created_by', 'cloned_from')

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

    Template mutation (update/delete) requires edit rights: the game's
    creator, a CREATOR collaborator, or a superuser. Legacy games with
    no recorded creator stay editable by any staff user. Runners
    personalise a template by cloning it (`POST {id}/clone/`).
    """

    permission_classes = [IsAdminUser]
    queryset = Game.objects.all().order_by('name')
    serializer_class = AdminGameSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def _require_edit(self, game):
        if not game.can_edit(self.request.user):
            raise PermissionDenied(
                'Only the game creator may modify this template. '
                'Clone the game to personalise and run your own copy.',
            )

    def perform_update(self, serializer):
        self._require_edit(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_edit(instance)
        instance.delete()

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """Clone this Game template for the calling user (§ cloning).

        Deep-copies template-owned data — rules config, challenge bank,
        TeamGroup taxonomy — and re-links the SAME Collections, so the
        clone shares Tower/Zone rows by PK instead of duplicating
        geometry. Records `cloned_from` and sets `created_by` to the
        cloning user. Optional body: {"name": ..., "slug": ...}.
        """
        source = self.get_object()

        slug = request.data.get('slug')
        if not slug:
            base = f'{source.slug}-clone'[:58]
            slug, counter = base, 2
            while Game.objects.filter(slug=slug).exists():
                slug = f'{base}-{counter}'
                counter += 1
        elif Game.objects.filter(slug=slug).exists():
            return Response(
                {'slug': 'A game with this slug already exists.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            clone = Game.objects.create(
                name=request.data.get('name') or f'{source.name} (clone)',
                slug=slug,
                base_point=source.base_point,
                base_zoom_level=source.base_zoom_level,
                # A fresh clone starts inactive; the runner activates it
                # when their event goes live.
                is_active=False,
                proximity_meters=source.proximity_meters,
                cooloff_minutes=source.cooloff_minutes,
                initial_bonus_default=source.initial_bonus_default,
                pause_freezes_floating_score=source.pause_freezes_floating_score,
                pause_restores_ownerships_on_resume=source.pause_restores_ownerships_on_resume,
                pause_rejects_submissions=source.pause_rejects_submissions,
                fail_point_penalty=source.fail_point_penalty,
                fail_cooloff_scaling=source.fail_cooloff_scaling,
                fail_tower_lockout_minutes=source.fail_tower_lockout_minutes,
                fail_difficulty_rollback=source.fail_difficulty_rollback,
                fail_counter_reset=source.fail_counter_reset,
                created_by=request.user,
                cloned_from=source,
            )
            # Share the geometry: link the SAME collections, never copy
            # Tower/Zone rows.
            clone.collections.set(source.collections.all())
            # Deep-copy the template layer: TeamGroup taxonomy and the
            # challenge bank (challenges keep pointing at the shared
            # repository towers).
            for group in TeamGroup.objects.filter(game=source):
                TeamGroup.objects.create(
                    game=clone, name=group.name, slug=group.slug,
                )
            for challenge in Challenge.objects.filter(game=source):
                Challenge.objects.create(
                    game=clone,
                    text=challenge.text,
                    tower=challenge.tower,
                    difficulty=challenge.difficulty,
                )
        return Response(
            self.get_serializer(clone).data, status=status.HTTP_201_CREATED,
        )

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
