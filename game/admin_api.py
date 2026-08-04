import random
import secrets

from django.contrib.gis.geos import GEOSException, Point, Polygon
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.challenge_types import REVIEW_MANUAL, TYPE_NFC_QR, TYPE_TEXT
from game.models import (
    NFC_MODE_LEGACY_URL,
    NFC_MODE_SECURE_TOKEN,
    ROLE_REQUIREMENT_NONE,
    Challenge,
    Collection,
    NfcTag,
    PresenceRequirement,
    TagScan,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    TowerLock,  # tower-locking
    TowerPhoto,
    Zone,
)
from game.scoping import (
    GameScopedViewSetMixin,
    SessionScopedViewSetMixin,
    _current_session,
)
from game.serializers import Base64ImageField
from organize.models import (
    Game,
    GameRole,
    IllegalTransition,
    Session,
    Team,
    TeamGroup,
    TeamMembership,
    TeamRole,
    UserProfile,
)


class RosterClosedError(APIException):
    """Team creation attempted while the session's roster is closed."""

    status_code = 409
    default_detail = 'Team rosters are closed in this session state.'
    default_code = 'roster_closed'


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


def _close_ring(vertices):
    """Turn a walked/tapped vertex list into a closed polygon ring.

    Vertices arrive as [[lng, lat], ...] in capture order (field
    authoring: one vertex per GPS mark or map tap). Needs at least 3
    distinct points; the ring is closed automatically.
    """
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise serializers.ValidationError(
            {'vertices': 'A zone needs at least 3 vertices.'},
        )
    ring = [tuple(v) for v in vertices]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    try:
        return Polygon(ring)
    except (GEOSException, ValueError) as exc:
        raise serializers.ValidationError({'vertices': f'Invalid polygon: {exc}'})


class TowerPhotoSerializer(serializers.ModelSerializer):
    """Reference photo payload (field-authoring, task 2.2).

    `image` accepts a multipart file OR a base64 data URL (the offline
    queue replays captures as JSON). `tower` / `captured_by` are set by
    the viewset, never by the client.
    """

    image = Base64ImageField(use_url=True)
    captured_by_username = serializers.CharField(
        source='captured_by.username', read_only=True, default=None,
    )

    class Meta:
        model = TowerPhoto
        fields = (
            'id', 'tower', 'image', 'caption',
            'captured_by', 'captured_by_username', 'captured_at',
        )
        read_only_fields = ('tower', 'captured_by', 'captured_at')


class AdminZoneSerializer(GeometryUsageMixin, serializers.ModelSerializer):
    """Staff Zone payload.

    Field authoring (task 2.3): `vertices` writes the boundary as
    [[lng, lat], ...] (walked or tapped order, ring closed server-side);
    `shape` reads back as GeoJSON. `collection` files a NEW zone into
    that Collection in the same call.
    """

    # Member towers via the many-to-many (tower-zone-topology) — shown
    # in the staff Zone editor; membership is edited from the Tower side.
    towers = serializers.SerializerMethodField()
    shape = serializers.SerializerMethodField(read_only=True)
    vertices = serializers.ListField(
        child=serializers.ListField(
            child=serializers.FloatField(), min_length=2, max_length=2,
        ),
        write_only=True, required=False, allow_null=True,
    )
    collection = serializers.PrimaryKeyRelatedField(
        queryset=Collection.objects.all(),
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = Zone
        fields = (
            'id', 'name', 'color', 'scoring_type', 'conquest_rule',
            'towers', 'shape', 'vertices', 'collection',
            'collections', 'games',
            # tower-visibility: per-zone fog threshold (null = inherit).
            'fog_reveal_coverage_pct',
        )

    def get_towers(self, zone):
        return [
            {'id': t.id, 'name': t.name}
            for t in zone.towers.all().order_by('name')
        ]

    def get_shape(self, zone):
        if zone.shape is None:
            return None
        return {
            'type': 'Polygon',
            'coordinates': [
                [list(point) for point in ring] for ring in zone.shape.coords
            ],
        }

    def validate(self, attrs):
        vertices = attrs.pop('vertices', None)
        if vertices is not None:
            if self.instance is None:
                self._require_create_collection_author(attrs)
            shape = _close_ring(vertices)
            if not shape.valid:
                raise serializers.ValidationError(
                    {
                        'vertices': (
                            'Self-intersecting or otherwise invalid polygon: '
                            f'{shape.valid_reason}'
                        ),
                    },
                )
            attrs['shape'] = self._clip_against_existing_zones(shape, attrs)
        return attrs

    def _require_create_collection_author(self, attrs):
        """Authorization wins over content validation (map-editor capability).

        `_close_ring`'s vertex-count/validity check and the
        existing-zone-wins clip below both raise 400s from inside
        `validate()`, which DRF runs BEFORE the view's `perform_create`
        permission gate (`CollectionAuthorGateMixin`). Without this early
        re-check, an unauthorised POST whose ring also happens to be
        invalid/overlapping would surface as 400 instead of the expected
        403. Mirrors `AdminZoneViewSet.perform_create`, which still runs
        too (defense in depth) -- this just makes sure authorization wins
        the ordering race for zone-boundary writes specifically.
        """
        collection = attrs.get('collection')
        request = self.context.get('request')
        if (
            collection is not None
            and request is not None
            and not collection.can_author(request.user)
        ):
            raise PermissionDenied(
                'You are not authorised to author into this collection. '
                'Ask its game creator for CREATOR collaboration, or clone the game.',
            )

    def _clip_against_existing_zones(self, shape, attrs):
        """Existing-zone-wins clipping (map-editor capability).

        Authoritative server-side pass: subtract the union of every
        OTHER zone sharing a Collection with this one from the incoming
        ring, so overlapping geometry can never be introduced -- even
        via a direct API call bypassing the desktop map editor's own
        (advisory, client-side) preview clip.

        Scope is the zone's own Collections on update, or the target
        `collection` (if any) on create -- a zone/collection combo not
        tied to any Collection has no defined "map" to avoid overlapping,
        so it is left untouched (legacy zones, standalone geometry).
        """
        if self.instance is not None:
            collections = list(self.instance.collections.all())
            exclude_pk = self.instance.pk
        else:
            collection = attrs.get('collection')
            collections = [collection] if collection is not None else []
            exclude_pk = None

        if not collections:
            return shape

        others = Zone.objects.filter(
            collections__in=collections, shape__isnull=False,
        ).distinct()
        if exclude_pk is not None:
            others = others.exclude(pk=exclude_pk)

        union = None
        for other in others:
            union = other.shape if union is None else union.union(other.shape)
        if union is None:
            return shape

        clipped = shape.difference(union)

        if clipped.empty or clipped.area <= 0:
            raise serializers.ValidationError(
                {
                    'vertices': (
                        'This zone is fully contained within existing zone(s). '
                        'Existing zones win overlaps -- draw a boundary outside '
                        'them, or edit the existing zone instead.'
                    ),
                },
            )

        if clipped.geom_type == 'MultiPolygon':
            # The new ring straddled a gap between existing zones and
            # got split into disconnected pieces -- keep the largest.
            clipped = max(clipped, key=lambda piece: piece.area)
        elif clipped.geom_type != 'Polygon':
            raise serializers.ValidationError(
                {
                    'vertices': (
                        'Clipping against existing zones left an unusable '
                        f'{clipped.geom_type} (likely a sliver along a shared '
                        'edge). Adjust the boundary and try again.'
                    ),
                },
            )

        return clipped

    def create(self, validated_data):
        collection = validated_data.pop('collection', None)
        zone = super().create(validated_data)
        if collection is not None:
            collection.zones.add(zone)
        return zone

    def update(self, instance, validated_data):
        # Target-collection filing is a create-time concern; adjusting an
        # existing zone never re-files it.
        validated_data.pop('collection', None)
        return super().update(instance, validated_data)


class AdminTowerSerializer(GeometryUsageMixin, serializers.ModelSerializer):
    """Staff Tower payload.

    Field authoring (task 2.1): create-at-GPS writes `lat`/`lng`
    (+ optional `authored_accuracy_m` capture provenance) and an optional
    target `collection` the new tower is filed into in the same call.
    `location` reads back as GeoJSON; `photos` lists reference photos.
    """

    # Many-to-many zone membership (tower-zone-topology).
    zones = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Zone.objects.all(), required=False,
    )
    location = serializers.SerializerMethodField(read_only=True)
    lat = serializers.FloatField(write_only=True, required=False, allow_null=True)
    lng = serializers.FloatField(write_only=True, required=False, allow_null=True)
    collection = serializers.PrimaryKeyRelatedField(
        queryset=Collection.objects.all(),
        write_only=True, required=False, allow_null=True,
    )
    photos = TowerPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = Tower
        fields = (
            'id', 'name', 'zones', 'category', 'is_active',
            'proximity_meters',
            # tower-visibility: the two per-tower axes (null = inherit
            # the Session/Game default).
            'discoverability', 'challenge_visibility',
            'initial_bonus', 'rfid_code',
            'location', 'lat', 'lng', 'authored_accuracy_m',
            'collection', 'photos', 'collections', 'games',
        )

    def get_location(self, tower):
        if tower.location is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [tower.location.x, tower.location.y],
        }

    def validate(self, attrs):
        lat = attrs.pop('lat', None)
        lng = attrs.pop('lng', None)
        if lat is not None and lng is not None:
            attrs['location'] = Point(lng, lat)
        elif (lat is None) != (lng is None):
            raise serializers.ValidationError('Provide both lat and lng, or neither.')
        if self.instance is None and 'location' not in attrs:
            raise serializers.ValidationError(
                'Creating a tower requires lat and lng.',
            )
        return attrs

    def create(self, validated_data):
        collection = validated_data.pop('collection', None)
        tower = super().create(validated_data)
        if collection is not None:
            collection.towers.add(tower)
            # A tower is only useful where its zones are also reachable:
            # file its member zones (many-to-many, tower-zone-topology)
            # into the same target collection (idempotent when a zone is
            # already a member).
            for zone in tower.zones.all():
                collection.zones.add(zone)
        return tower

    def update(self, instance, validated_data):
        # Target-collection filing is a create-time concern; updating an
        # existing tower never re-files it.
        validated_data.pop('collection', None)
        # Removing a zone's last member tower violates the
        # at-least-one-tower invariant; surface the model-layer guard's
        # Django ValidationError as a DRF 400 instead of a 500. The
        # explicit atomic() gives the guard's raise a savepoint so an
        # enclosing transaction stays usable.
        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'zones': exc.messages})


class AdminTeamSerializer(serializers.ModelSerializer):
    # Read-only `game` derived from session.game for convenience in the
    # staff UI. Writes always go through `session`.
    game = serializers.IntegerField(source='session.game_id', read_only=True)
    active_member_count = serializers.SerializerMethodField()
    is_ready = serializers.SerializerMethodField()
    members_needed = serializers.SerializerMethodField()
    captain_username = serializers.CharField(
        source='captain.username', read_only=True, default=None,
    )

    class Meta:
        model = Team
        fields = (
            'id', 'name', 'session', 'game',
            'group', 'color', 'description',
            'active_member_count', 'is_ready', 'members_needed',
            # Team-formation fields: captain + per-team confirmation
            # override (null = inherit Game default) + untied join code.
            'captain', 'captain_username', 'team_join_confirmation',
            'join_code',
        )
        read_only_fields = ('join_code',)

    def get_active_member_count(self, team):
        return team.active_member_count()

    def get_is_ready(self, team):
        return team.is_ready()

    def get_members_needed(self, team):
        return team.members_needed()


class AdminTeamGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamGroup
        fields = ('id', 'name', 'game', 'slug')


class AdminChallengeSerializer(serializers.ModelSerializer):
    """Staff-side challenge payload.

    Unlike the player serializers this DOES expose `validation_code` —
    staff author it and hand it to the venue (printable handout).
    """

    class Meta:
        model = Challenge
        fields = (
            'id', 'game', 'text', 'tower', 'difficulty',
            'type', 'validation_code', 'type_config', 'review_mode',
            'role_requirement_mode', 'required_roles', 'require_holders_present',
            # presence-rules: null = no presence requirement.
            'presence_requirement',
        )

    def validate(self, attrs):
        """team-roles config validation (task 2.3) + challenge-type config.

        `required_roles` must belong to the challenge's Game, and a
        non-NONE `role_requirement_mode` needs a non-empty role set.
        An NFC_QR challenge needs a `validation_code` unless forced to
        MANUAL review; `type_config` must be a JSON object and
        `single_use`, when present, a boolean.
        """
        instance = self.instance

        def resolved(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field) if instance else default

        challenge_type = resolved('type', TYPE_TEXT)
        type_config = resolved('type_config', {}) or {}
        if not isinstance(type_config, dict):
            raise serializers.ValidationError(
                'type_config must be a JSON object.',
            )
        if 'single_use' in type_config and not isinstance(type_config['single_use'], bool):
            raise serializers.ValidationError(
                'type_config.single_use must be a boolean.',
            )
        if (
            challenge_type == TYPE_NFC_QR
            and not resolved('validation_code')
            and resolved('review_mode') != REVIEW_MANUAL
        ):
            raise serializers.ValidationError(
                'An NFC_QR challenge needs a validation_code (the code the '
                'venue hands out) unless its review_mode is forced to MANUAL.',
            )

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


class CollectionAuthorGateMixin:
    """Field-authoring permission gate (task 2.5, `game-authoring-roles`).

    Filing geometry into a Collection — or mutating geometry already
    shared through Collections — requires the caller to be authorised to
    author EVERY Collection touched (`Collection.can_author`, which
    resolves to `Game.can_edit` on the referencing Games). Geometry in
    no Collection stays plain staff-editable, as before.
    """

    def _require_collection_author(self, collection):
        if collection is not None and not collection.can_author(self.request.user):
            raise PermissionDenied(
                'You are not authorised to author into this collection. '
                'Ask its game creator for CREATOR collaboration, or clone the game.',
            )

    def _require_geometry_author(self, obj):
        for collection in obj.collections.all():
            self._require_collection_author(collection)


class AdminZoneViewSet(CollectionAuthorGateMixin, CollectionFilterMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for repository Zones.

    `?tower=<id>` narrows to the zones a tower belongs to (many-to-many
    membership, tower-zone-topology).

    Field authoring: boundaries are writable as `vertices` (walked or
    tapped [[lng, lat], ...]); new zones are filed into the target
    `collection` in the same call. Writes into a Collection are gated
    by `Collection.can_author` (task 2.5).
    """

    permission_classes = [IsAdminUser]
    queryset = Zone.objects.all().order_by('name')
    serializer_class = AdminZoneSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tower_id = self.request.query_params.get('tower')
        if tower_id:
            qs = qs.filter(towers=tower_id)
        return qs

    def perform_create(self, serializer):
        self._require_collection_author(serializer.validated_data.get('collection'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_geometry_author(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_geometry_author(instance)
        instance.delete()


class AdminTowerViewSet(CollectionAuthorGateMixin, CollectionFilterMixin, viewsets.ModelViewSet):
    """Staff-only CRUD for repository Towers + activate/deactivate/unassign actions.

    `?zone=<id>` narrows to one zone's member towers (many-to-many
    membership, tower-zone-topology).

    Field authoring: create-at-GPS via `lat`/`lng` (+ optional
    `authored_accuracy_m` provenance and a target `collection` the new
    tower is filed into in one call, task 2.1); reference-photo
    endpoints under {id}/photos/ (task 2.2); attach-challenge action
    (task 2.4). Collection-touching writes are gated by
    `Collection.can_author` (task 2.5).
    """

    permission_classes = [IsAdminUser]
    queryset = Tower.objects.all().order_by('name').prefetch_related('photos__captured_by')
    serializer_class = AdminTowerSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        zone_id = self.request.query_params.get('zone')
        if zone_id:
            qs = qs.filter(zones=zone_id)
        return qs

    def perform_create(self, serializer):
        self._require_collection_author(serializer.validated_data.get('collection'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_geometry_author(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_geometry_author(instance)
        # Deleting a zone's last member tower is rejected by the
        # at-least-one-tower invariant guard (tower-zone-topology).
        try:
            with transaction.atomic():
                instance.delete()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'detail': exc.messages})

    @action(detail=True, methods=['get', 'post'])
    def photos(self, request, pk=None):
        """Reference photos: GET lists, POST uploads (multipart or base64)."""
        tower = self.get_object()
        if request.method == 'POST':
            self._require_geometry_author(tower)
            serializer = TowerPhotoSerializer(
                data=request.data, context=self.get_serializer_context(),
            )
            serializer.is_valid(raise_exception=True)
            photo = serializer.save(tower=tower, captured_by=request.user)
            return Response(
                TowerPhotoSerializer(
                    photo, context=self.get_serializer_context(),
                ).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(
            TowerPhotoSerializer(
                tower.photos.all(), many=True,
                context=self.get_serializer_context(),
            ).data,
        )

    @action(
        detail=True, methods=['delete'],
        url_path=r'photos/(?P<photo_id>[0-9]+)',
    )
    def delete_photo(self, request, pk=None, photo_id=None):
        tower = self.get_object()
        self._require_geometry_author(tower)
        photo = get_object_or_404(TowerPhoto, pk=photo_id, tower=tower)
        photo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='attach-challenge')
    def attach_challenge(self, request, pk=None):
        """Field action (task 2.4): attach a Challenge to this tower.

        Body: {"challenge": <id>} re-points an existing challenge at
        this tower, or {"game": <id>, "text": ..., "difficulty": <n>}
        creates one on the spot. The challenge bank is Game template
        data, so both paths require `Game.can_edit`.
        """
        tower = self.get_object()
        challenge_id = request.data.get('challenge')
        if challenge_id:
            challenge = (
                Challenge.objects.select_related('game')
                .filter(pk=challenge_id).first()
            )
            if challenge is None:
                return Response(
                    {'detail': 'Challenge not found.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            self._require_challenge_bank_edit(challenge.game)
            challenge.tower = tower
            challenge.save(update_fields=['tower'])
            return Response(AdminChallengeSerializer(challenge).data)

        game = Game.objects.filter(pk=request.data.get('game') or 0).first()
        text = (request.data.get('text') or '').strip()
        if game is None or not text:
            return Response(
                {'detail': 'Provide either "challenge", or "game" and "text".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        self._require_challenge_bank_edit(game)
        try:
            difficulty = int(request.data.get('difficulty', 1))
        except (TypeError, ValueError):
            difficulty = 1
        challenge = Challenge.objects.create(
            game=game, tower=tower, text=text, difficulty=max(1, difficulty),
        )
        return Response(
            AdminChallengeSerializer(challenge).data,
            status=status.HTTP_201_CREATED,
        )

    def _require_challenge_bank_edit(self, game):
        if game is not None and not game.can_edit(self.request.user):
            raise PermissionDenied(
                'Only the game creator may modify its challenge bank. '
                'Clone the game to personalise it.',
            )

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
# Presence requirements (presence-rules)
# ---------------------------------------------------------------------------


class AdminPresenceRequirementSerializer(serializers.ModelSerializer):
    challenge_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PresenceRequirement
        fields = (
            'id', 'name', 'min_members_present', 'method',
            'geofence_radius_meters', 'window_seconds', 'challenge_count',
        )

    def get_challenge_count(self, requirement):
        return requirement.challenges.count()

    def validate_min_members_present(self, value):
        if value < 1:
            raise serializers.ValidationError(
                'At least one member must be required present.',
            )
        return value


class AdminPresenceRequirementViewSet(viewsets.ModelViewSet):
    """Staff CRUD for reusable presence requirements (presence-rules).

    A requirement is a named, shareable row ("≥2 people, geofence,
    30s window") referenced by any number of Challenges; deleting one
    detaches it (`SET_NULL`) without touching the Challenges.
    """

    permission_classes = [IsAdminUser]
    queryset = PresenceRequirement.objects.all().order_by('name')
    serializer_class = AdminPresenceRequirementSerializer


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


# ---------------------------------------------------------------------------
# nfc-native-and-secure-links: tag provisioning + scan audit
# ---------------------------------------------------------------------------


class AdminNfcTagSerializer(serializers.ModelSerializer):
    """Staff payload for provisioned tags.

    `token` is minted server-side and read-only; `app_link` /
    `ndef_payload` give the writable provisioning data (also exposed as
    the dedicated `ndef` / `qr` actions).
    """

    app_link = serializers.SerializerMethodField()
    target_summary = serializers.SerializerMethodField()
    scan_count = serializers.SerializerMethodField()

    class Meta:
        model = NfcTag
        fields = (
            'id', 'token', 'mode', 'tower', 'challenge',
            'label', 'hidden_hint', 'is_active',
            'expected_counter', 'last_counter',
            'app_link', 'target_summary', 'scan_count',
            'created_by', 'created_at',
        )
        read_only_fields = ('token', 'last_counter', 'created_by', 'created_at')

    def get_app_link(self, tag):
        return tag.app_link()

    def get_target_summary(self, tag):
        if tag.tower_id:
            return {'kind': 'tower', 'id': tag.tower_id, 'name': tag.tower.name}
        if tag.challenge_id:
            return {
                'kind': 'challenge', 'id': tag.challenge_id,
                'name': str(tag.challenge)[:80],
            }
        return None

    def get_scan_count(self, tag):
        return tag.scans.count()

    def validate(self, attrs):
        """Friendly-400 mirror of NfcTag.clean() (task 1.3)."""
        instance = self.instance

        def resolved(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field) if instance else default

        mode = resolved('mode', NFC_MODE_SECURE_TOKEN)
        tower = resolved('tower')
        challenge = resolved('challenge')
        if mode == NFC_MODE_SECURE_TOKEN:
            if bool(tower) == bool(challenge):
                raise serializers.ValidationError(
                    'A SECURE_TOKEN tag must target exactly one of a Tower or a Challenge.',
                )
            if challenge is not None and challenge.tower_id is None:
                raise serializers.ValidationError(
                    'A challenge-targeted tag needs a tower-bound challenge.',
                )
        else:
            if challenge is not None or tower is None:
                raise serializers.ValidationError(
                    'A LEGACY_URL tag must target a Tower (not a Challenge).',
                )
            if tower.category != Tower.CATEGORY_RFID or not tower.rfid_code:
                raise serializers.ValidationError(
                    'A LEGACY_URL tag mirrors an RFID-category tower with an rfid_code.',
                )
        return attrs


class AdminTagScanSerializer(serializers.ModelSerializer):
    tag_label = serializers.SerializerMethodField()
    player_username = serializers.CharField(
        source='player.username', read_only=True, default=None,
    )

    class Meta:
        model = TagScan
        fields = (
            'id', 'tag', 'tag_label', 'player', 'player_username',
            'session', 'timestamp', 'outcome',
            'lat', 'lng', 'accuracy', 'counter',
        )

    def get_tag_label(self, scan):
        return scan.tag.label or scan.tag.token[:8]


class AdminNfcTagViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for NfcTags + provisioning exports + scan audit.

    Mint (POST — the token is generated server-side), bind to a tower or
    challenge, edit, deactivate (PATCH is_active=false) or delete.
    Filters: ?tower=, ?challenge=, ?mode=. `GET {id}/ndef/` returns the
    writable NDEF records, `GET {id}/qr/` a printable PNG of the
    app-link, `GET scan-audit/` the TagScan audit list (?tag= filter).
    """

    permission_classes = [IsAdminUser]
    queryset = (
        NfcTag.objects
        .select_related('tower', 'challenge', 'challenge__tower')
        .order_by('-created_at')
    )
    serializer_class = AdminNfcTagSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tower_id = self.request.query_params.get('tower')
        if tower_id:
            qs = qs.filter(tower_id=tower_id)
        challenge_id = self.request.query_params.get('challenge')
        if challenge_id:
            qs = qs.filter(challenge_id=challenge_id)
        mode = self.request.query_params.get('mode')
        if mode:
            qs = qs.filter(mode=mode.upper())
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def ndef(self, request, pk=None):
        """The exact records to write to the physical tag (task 5.2)."""
        return Response(self.get_object().ndef_payload())

    @action(detail=True, methods=['get'])
    def qr(self, request, pk=None):
        """Printable QR PNG of the app-link (stickers / camera fallback)."""
        import io

        import qrcode
        from django.http import HttpResponse

        tag = self.get_object()
        if tag.mode == NFC_MODE_LEGACY_URL:
            payload = tag.ndef_payload()['records'][0]['uri']
        else:
            payload = tag.app_link()
        buf = io.BytesIO()
        qrcode.make(payload).save(buf, format='PNG')
        return HttpResponse(buf.getvalue(), content_type='image/png')

    @action(detail=False, methods=['get'], url_path='scan-audit')
    def scan_audit(self, request):
        """Recent TagScan audit rows (newest first, capped at 200)."""
        scans = TagScan.objects.select_related('tag', 'player').order_by('-timestamp')
        tag_id = request.query_params.get('tag')
        if tag_id:
            scans = scans.filter(tag_id=tag_id)
        session_id = request.query_params.get('session')
        if session_id:
            scans = scans.filter(session_id=session_id)
        return Response(AdminTagScanSerializer(scans[:200], many=True).data)


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


TEAM_RULE_FIELDS = (
    'min_teams', 'max_teams', 'min_members_per_team', 'max_members_per_team',
)

# BLE proximity substrate + dementors mode knobs (mode-dementors-ble):
# Game defaults with nullable Session overrides, same shape as the
# Phase-10 knobs above.
DEMENTOR_BLE_FIELDS = (
    'require_ble_capable', 'ble_report_interval_seconds',
    'ble_scan_duty_cycle_percent', 'ble_freshness_window_seconds',
    'ble_identity_rotation_minutes', 'ble_rssi_very_close_dbm',
    'ble_rssi_near_dbm', 'ble_rssi_hysteresis_db',
    'dementors_enabled', 'dementor_initial_dementors',
    'dementor_starting_energy', 'dementor_drain_per_second',
    'dementor_drain_range_bucket', 'dementor_empty_outcome',
    'dementor_safety_in_numbers', 'dementor_reverse_group_size',
    'dementor_reverse_hold_seconds', 'dementor_conversion_threshold',
    'dementor_restore_per_second', 'dementor_wizard_regen_per_second',
    'dementor_tick_seconds',
)


def _validate_team_rules(resolved):
    """Shared team-rule sanity checks for the Game and Session serializers.

    `resolved(field)` returns the value a field would have after the
    write (payload value, else instance value, else Game default).
    Minima must be ≥ 1; a non-zero maximum (0 = no cap) may not be
    smaller than its corresponding minimum.
    """
    errors = {}
    for field in ('min_teams', 'min_members_per_team'):
        value = resolved(field)
        if value is not None and value < 1:
            errors[field] = 'Must be at least 1.'
    for min_field, max_field in (
        ('min_teams', 'max_teams'),
        ('min_members_per_team', 'max_members_per_team'),
    ):
        minimum = resolved(min_field)
        maximum = resolved(max_field)
        if minimum and maximum and maximum < minimum:
            errors[max_field] = (
                f'A non-zero maximum cannot be smaller than {min_field} ({minimum}).'
            )
    if errors:
        raise serializers.ValidationError(errors)


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
            'id', 'slug', 'name', 'mode',
            'base_point', 'base_lat', 'base_lng',
            'base_zoom_level', 'is_active',
            'proximity_meters', 'cooloff_minutes', 'initial_bonus_default',
            # Conquest + scoring-cadence defaults
            # (zone-conquest-and-scoring-config).
            'zone_conquest_rule', 'score_time_unit',
            # Phase 10 day-pausing knobs.
            'pause_freezes_floating_score',
            'pause_restores_ownerships_on_resume',
            'pause_rejects_submissions',
            # Phase 10 failure-consequence knobs.
            'fail_point_penalty', 'fail_cooloff_scaling',
            'fail_tower_lockout_minutes', 'fail_difficulty_rollback',
            'fail_counter_reset',
            # Team-composition rule defaults (maxima: 0 = no cap).
            'min_teams', 'max_teams',
            'min_members_per_team', 'max_members_per_team',
            # Team-formation knobs (defaults preserve staff-only rosters).
            'allow_player_team_creation', 'team_join_confirmation',
            # Live-location knobs (tracking defaults OFF).
            'location_tracking_enabled', 'location_ping_interval_seconds',
            'location_visibility', 'location_retention_days',
            'location_consent_text',
            # Presence-rules knobs (defaults preserve base behavior).
            'togetherness_mode', 'teammate_visibility_mode',
            'teammate_visibility_count', 'presence_window_seconds',
            # Realtime + push defaults (realtime-and-notifications).
            'realtime_enabled', 'push_notifications_enabled',
            # NFC capture-mode knobs (defaults preserve legacy URLs).
            'nfc_secure_mode', 'nfc_require_app', 'nfc_replay_hardening',
            # Tower-locking knobs (default FREE_FOR_ALL = today's behavior).
            'tower_lock_mode', 'tower_lock_finish_minutes',
            # BLE proximity + dementors mode defaults (mode-dementors-ble).
            *DEMENTOR_BLE_FIELDS,
            # Tower-visibility defaults (tower-visibility capability).
            'tower_discoverability_default', 'challenge_visibility_default',
            'fog_reveal_coverage_pct_default', 'reveal_other_teams_ownership',
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

    def validate(self, attrs):
        def resolved(field):
            if field in attrs:
                return attrs[field]
            if self.instance is not None:
                return getattr(self.instance, field)
            return Game._meta.get_field(field).default

        _validate_team_rules(resolved)
        return attrs

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

        Delegates to `Game.clone()`, which deep-copies template-owned
        data — every config knob, challenge bank (required_roles
        remapped), GameRoles, TeamGroup taxonomy — and re-links the
        SAME Collections, so the clone shares Tower/Zone rows by PK
        instead of duplicating geometry. Records `cloned_from` and sets
        `created_by` to the cloning user.
        Optional body: {"name": ..., "slug": ...}.
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

        clone = source.clone(
            slug,
            name=request.data.get('name') or f'{source.name} (clone)',
            created_by=request.user,
        )
        return Response(
            self.get_serializer(clone).data, status=status.HTTP_201_CREATED,
        )

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


class SessionStartBlocked(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Session cannot start: team composition rules are not met.'
    default_code = 'start_blocked'


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
            # Conquest-rule / scoring-time-unit overrides (null = inherit
            # the Game default; zone-conquest-and-scoring-config).
            'zone_conquest_rule', 'score_time_unit',
            # Team-rule overrides (null = inherit; maxima: 0 = no cap).
            'min_teams', 'max_teams',
            'min_members_per_team', 'max_members_per_team',
            # Team-formation override (null = inherit Game default).
            'allow_player_team_creation',
            # Live-location overrides (null = inherit Game default).
            'location_tracking_enabled', 'location_ping_interval_seconds',
            'location_visibility', 'location_retention_days',
            'location_consent_text',
            # Presence-rules overrides (null = inherit Game default).
            'togetherness_mode', 'teammate_visibility_mode',
            'teammate_visibility_count', 'presence_window_seconds',
            # Realtime + push overrides (null = inherit Game default).
            'realtime_enabled', 'push_notifications_enabled',
            # NFC capture-mode overrides (null = inherit Game default).
            'nfc_secure_mode', 'nfc_require_app', 'nfc_replay_hardening',
            # Tower-locking overrides (null = inherit Game default).
            'tower_lock_mode', 'tower_lock_finish_minutes',
            # Game-mode override (mode-trail-discovery; null = inherit).
            'mode',
            # BLE proximity + dementors overrides (null = inherit).
            *DEMENTOR_BLE_FIELDS,
            # Tower-visibility overrides (null = inherit Game default).
            'tower_discoverability_default', 'challenge_visibility_default',
            'fog_reveal_coverage_pct_default', 'reveal_other_teams_ownership',
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

    def validate(self, attrs):
        game = attrs.get('game') or (
            self.instance.game if self.instance is not None else None
        )

        def resolved(field):
            if field in attrs:
                value = attrs[field]
            elif self.instance is not None:
                value = getattr(self.instance, field)
            else:
                value = None
            if value is None and game is not None:
                return getattr(game, field)
            return value

        _validate_team_rules(resolved)
        return attrs


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
            if exc.blockers is not None:
                payload['blockers'] = exc.blockers
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
    def start_blockers(self, request, pk=None):
        """Read-only start-gate check for the staff UI start control.

        Returns the same blockers the activation path enforces, plus a
        per-team readiness summary, so the UI can disable/annotate the
        start button without attempting the transition.
        """
        session = self.get_object()
        blockers = session.start_blockers()
        teams = [
            {
                'id': team.id,
                'name': team.name,
                'color': team.color,
                'active_member_count': team.active_member_count(),
                'is_ready': team.is_ready(),
                'members_needed': team.members_needed(),
            }
            for team in session.teams.order_by('name', 'id')
        ]
        return Response({
            'can_start': not blockers,
            'blockers': blockers,
            'min_members_per_team': session.effective('min_members_per_team'),
            'teams': teams,
        })

    @action(detail=True, methods=['get'], url_path='discovery-matrix')
    def discovery_matrix(self, request, pk=None):
        """Team × tower discovery state for the session (tower-visibility UI).

        Lists the session's teams, the game's non-always-visible towers
        (any tower whose effective discoverability is not VISIBLE), and
        the existing TowerDiscovery cells, so staff can see who found
        what and reveal towers by hand (POST /api/staff/discovery/reveal/).
        """
        from game.discovery import _visible_now_q
        from game.models import TowerDiscovery
        session = self.get_object()
        default = session.effective('tower_discoverability_default')
        towers = list(
            session.towers()
            .filter(is_active=True)
            .exclude(_visible_now_q(default))
            .order_by('name'),
        )
        teams = list(session.teams.order_by('name'))
        discoveries = (
            TowerDiscovery.objects
            .filter(session=session)
            .select_related('discovered_by')
        )
        cells = [
            {
                'team_id': d.team_id,
                'tower_id': d.tower_id,
                'method': d.method,
                'discovered_at': d.discovered_at,
                'discovered_by': (
                    d.discovered_by.username if d.discovered_by else None
                ),
            }
            for d in discoveries
        ]
        return Response({
            'session': session.id,
            'default_discoverability': default,
            'teams': [
                {'id': t.id, 'name': t.name, 'color': t.color} for t in teams
            ],
            'towers': [
                {
                    'id': t.id,
                    'name': t.name,
                    'discoverability': t.effective_discoverability(session=session),
                }
                for t in towers
            ],
            'discoveries': cells,
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


# ---------------------------------------------------------------------------
# tower-locking: staff visibility of active locks + cancel
# ---------------------------------------------------------------------------


class StaffTowerLockSerializer(serializers.ModelSerializer):
    tower_name = serializers.CharField(source='tower.name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)
    team_color = serializers.CharField(source='team.color', read_only=True)
    group_name = serializers.CharField(
        source='group.name', read_only=True, default=None,
    )
    remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = TowerLock
        fields = (
            'id', 'tower', 'tower_name', 'team', 'team_name', 'team_color',
            'group', 'group_name', 'started_at', 'expires_at',
            'released_at', 'release_reason', 'remaining_seconds',
        )

    def get_remaining_seconds(self, lock):
        return lock.remaining_seconds()


class StaffTowerLockViewSet(SessionScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Staff-only view of the current session's ACTIVE tower locks.

    `GET /api/staff/tower_locks/` lists active locks (released and
    lapsed locks are excluded — lazy expiry); `POST {id}/cancel/`
    force-releases one with `release_reason=CANCELLED`.
    """

    permission_classes = [IsAdminUser]
    queryset = (
        TowerLock.objects
        .select_related('tower', 'team', 'group')
        .order_by('expires_at')
    )
    serializer_class = StaffTowerLockSerializer
    session_scope_field = 'team__session'

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, 'action', None) == 'list':
            return qs.filter(
                released_at__isnull=True, expires_at__gt=timezone.now(),
            )
        return qs

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        lock = self.get_object()
        if not lock.is_active():
            return Response(
                {'detail': 'Lock is no longer active.'},
                status=status.HTTP_409_CONFLICT,
            )
        lock.release(TowerLock.CANCELLED)
        return Response(self.get_serializer(lock).data)
