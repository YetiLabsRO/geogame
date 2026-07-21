from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from game.challenge_types import (
    REVIEW_AUTO,
    REVIEW_MANUAL,
    TYPE_RFID,
    get_handler,
)
from game.models import (
    Challenge,
    PresenceCheck,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    Tower,
    Zone,
    effective_proximity,
)
from game.trail import read_only_gate_step
from organize.models import Team


class SessionPausedError(APIException):
    status_code = 409
    default_detail = 'Sesiunea este în pauză; trimiterile sunt oprite.'
    default_code = 'session_paused'


class TowerLockedError(APIException):
    status_code = 409
    default_detail = 'Turn blocat temporar după eșecuri consecutive.'
    default_code = 'tower_locked'


class ZoneSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Zone
        fields = ["name", "color", "scoring_type", "shape", "team_color", "conquest_rule"]

    team_color = serializers.SerializerMethodField()

    def get_team_color(self, zone):
        group = int(self.context.get("group", 0))
        if group:
            control_team_ids = zone.zone_control(group=group)
            teams = Team.objects.filter(pk__in=control_team_ids)
            if teams.count() > 1:
                return "#FFFFFF"
            elif teams.count() == 1:
                return teams.first().color
        return "#000000"


class TowerSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Tower
        fields = [
            "name", "location", "zones", "category", "is_active",
            "ownership", "id", "has_initial_bonus", "proximity_meters",
        ]

    # Many-to-many zone membership (tower-zone-topology): a list of zone
    # ids, never a single zone.
    zones = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    ownership = serializers.SerializerMethodField()
    has_initial_bonus = serializers.SerializerMethodField()

    def get_ownership(self, obj):
        #   TODO: fix this
        return TeamSerializer(obj.tower_control(1)).data

    def get_has_initial_bonus(self, obj: Tower):
        return obj.initial_bonus != 0


class TeamSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source='group.name', read_only=True, default=None)
    group_slug = serializers.CharField(source='group.slug', read_only=True, default=None)
    members = serializers.SerializerMethodField()
    active_member_count = serializers.SerializerMethodField()
    is_ready = serializers.SerializerMethodField()
    members_needed = serializers.SerializerMethodField()
    # Optional on create — the viewset fills in a random color for
    # player-created teams (team-formation capability).
    color = serializers.CharField(required=False)

    class Meta:
        model = Team
        fields = [
            "id", "name", "group", "group_name", "group_slug",
            "current_score", "color", "members",
            "active_member_count", "is_ready", "members_needed",
        ]

    def get_members(self, team):
        """Active members with their in-game roles (team-roles)."""
        memberships = (
            team.memberships
            .filter(is_active=True)
            .select_related('user__user')
            .prefetch_related('roles__role')
        )
        return [
            {
                'user_id': m.user.user.id,
                'username': m.user.user.username,
                'roles': [
                    {'id': tr.role.id, 'slug': tr.role.slug, 'name': tr.role.name}
                    for tr in m.roles.all()
                ],
            }
            for m in memberships
        ]

    def get_active_member_count(self, team):
        return team.active_member_count()

    def get_is_ready(self, team):
        return team.is_ready()

    def get_members_needed(self, team):
        return team.members_needed()


class ChallengeSerializer(serializers.HyperlinkedModelSerializer):
    """Player-facing challenge payload.

    Emits the challenge `type`, its effective review mode and the
    submission payload the client must supply — but NEVER the raw
    `validation_code` (players must obtain it at the venue).
    """

    required_role_slugs = serializers.SerializerMethodField()
    effective_review_mode = serializers.SerializerMethodField()
    required_payload = serializers.SerializerMethodField()

    class Meta:
        model = Challenge
        fields = [
            "text", "tower", "difficulty", "type",
            "effective_review_mode", "required_payload",
            "role_requirement_mode", "required_role_slugs",
        ]

    def get_required_role_slugs(self, challenge):
        return [role.slug for role in challenge.required_roles.all()]

    def get_effective_review_mode(self, challenge):
        return challenge.effective_review_mode()

    def get_required_payload(self, challenge):
        return challenge.required_payload()


class Base64ImageField(serializers.ImageField):

    def to_internal_value(self, data):
        import base64
        import uuid

        from django.core.files.base import ContentFile

        if isinstance(data, str):
            if 'data:' in data and ';base64,' in data:
                header, data = data.split(';base64,')

            try:
                decoded_file = base64.b64decode(data)
            except TypeError:
                self.fail('invalid_image')

            file_name = str(uuid.uuid4())[:12]
            file_extension = self.get_file_extension(file_name, decoded_file)
            complete_file_name = "%s.%s" % (file_name, file_extension, )
            data = ContentFile(decoded_file, name=complete_file_name)

        return super(Base64ImageField, self).to_internal_value(data)

    def get_file_extension(self, file_name, decoded_file):
        import imghdr

        extension = imghdr.what(file_name, decoded_file)
        extension = "jpg" if extension == "jpeg" else extension

        return extension


class TeamTowerChallengeSerializer(serializers.ModelSerializer):
    """Write-side payload for POST /api/team_tower_challenges/.

    Requires an authenticated user with an active TeamMembership. Team is
    derived from that membership — NEVER sent by the client. RFID captures
    send `rfid_code` and skip `tower`; the serializer resolves the matching
    active RFID tower and dispatches through the RFID handler.

    Check order: membership → location consent (live-location) →
    tower/RFID resolution + challenge-type handler resolution +
    required-payload check → GPS proximity (per-tower effective radius) →
    presence requirement (presence-rules) → challenge role requirement
    (team-roles) → paused session → failure lockout → type outcome
    resolution. The consent gate sits right after membership because it
    is a session-level "may this player play at all" precondition,
    independent of the tower. The handler/payload check runs right after
    tower resolution because an unknown type or a malformed payload is a
    request-shape error (like an unknown RFID code), not a game-state
    one. Presence runs directly after the submitter's own proximity
    check (it extends it to teammates), so "you are too far" wins over
    "your team is not together", which in turn wins over "you lack a
    role"; the pause/lockout checks stay before outcome resolution. The
    outcome resolution runs LAST so an auto-validated scan can never
    bypass the proximity/presence/role/pause/lockout gates: a paused
    hold stays PENDING, and a presence photo fallback never auto-resolves
    (it holds for staff review, even for RFID/scan captures).
    """

    class Meta:
        model = TeamTowerChallenge
        fields = [
            "id",
            "photo",
            "challenge",
            "tower",
            "rfid_code",
            "submitted_code",
            "lng",
            "lat",
            "response_text",
            "outcome",
            "team",
            "submitted_by",
            "timestamp_submitted",
        ]
        read_only_fields = ("id", "team", "submitted_by", "outcome", "timestamp_submitted")

    photo = Base64ImageField(max_length=None, use_url=True, required=False, allow_empty_file=True, allow_null=True)
    tower = serializers.PrimaryKeyRelatedField(queryset=Tower.objects.all(), required=False, allow_null=True)
    rfid_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    submitted_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    lat = serializers.FloatField(required=True, write_only=True)
    lng = serializers.FloatField(required=True, write_only=True)

    def validate(self, attrs):
        user = self.context['request'].user
        membership = user.profile.memberships.filter(is_active=True).select_related('team').first()
        if membership is None:
            raise serializers.ValidationError(
                "Nu ești membru al unei echipe active.",
            )
        attrs['_team'] = membership.team

        # live-location: playing a location-enabled session requires
        # standing consent to its location rules (no-op when the
        # effective config has tracking off — the default).
        from game.location_api import location_consent_blocker
        consent_blocker = location_consent_blocker(user, membership.team.session)
        if consent_blocker is not None:
            raise consent_blocker

        rfid_code = attrs.get('rfid_code') or None
        tower = attrs.get('tower')
        challenge = attrs.get('challenge')
        submitted_code = attrs.get('submitted_code') or None

        if rfid_code:
            # Public RFID capture path (/tower/rfid/<code>/): resolve the
            # tower by its code, then dispatch through the RFID handler
            # exactly like a hand-built RFID scan submission.
            try:
                tower = Tower.objects.get(
                    rfid_code=rfid_code,
                    is_active=True,
                    category=Tower.CATEGORY_RFID,
                )
            except Tower.DoesNotExist:
                raise serializers.ValidationError("Cod RFID necunoscut sau turn inactiv.")
            attrs['tower'] = tower
            submitted_code = attrs['submitted_code'] = rfid_code
            handler = get_handler(TYPE_RFID)
            effective_mode = handler.review_mode
        else:
            if not tower:
                raise serializers.ValidationError("Trebuie un turn sau un cod RFID.")
            if challenge is not None:
                # Type dispatch: an unregistered type is rejected safely
                # (never captures), and the type's required payload must
                # be present before anything else is evaluated.
                handler = get_handler(challenge.type)
                if handler is None:
                    raise serializers.ValidationError(
                        f"Tip de provocare necunoscut: {challenge.type}.",
                    )
                error = handler.payload_error(
                    submitted_code=submitted_code, photo=attrs.get('photo'),
                )
                if error:
                    raise serializers.ValidationError(error)
                effective_mode = challenge.effective_review_mode()
            elif tower.category == Tower.CATEGORY_RFID and submitted_code:
                # Tower.category == RFID stays the trigger for the RFID
                # handler: a challenge-less scan against an RFID tower
                # takes the same auto path as the public code route.
                handler = get_handler(TYPE_RFID)
                effective_mode = handler.review_mode
            else:
                # Challenge-less free-form submission — the pre-change
                # manual path, unchanged.
                handler = None
                effective_mode = REVIEW_MANUAL

        attrs['_handler'] = handler
        attrs['_effective_mode'] = effective_mode

        if not attrs.get('lat') or not attrs.get('lng'):
            raise serializers.ValidationError("Dacă nu ești la turn, nu poți face provocarea!")

        point = Point(attrs['lng'], attrs['lat'])
        # Per-tower capture radius when set, else the game-wide default
        # (zone-conquest-and-scoring-config: effective proximity).
        proximity = effective_proximity(tower, attrs['_team'].session.game)
        if not Tower.objects.filter(
            pk=tower.id,
            location__distance_lte=(point, Distance(m=proximity)),
        ).exists():
            raise serializers.ValidationError(
                f"Trebuie să fii la maxim {proximity} de metri de turn "
                "pentru a putea face provocarea!",
            )

        # presence-rules: enforce the challenge's effective presence
        # requirement right after the submitter's own proximity check.
        # The fully-default resolution (no PresenceRequirement,
        # SPLIT_ALLOWED, window 0) is a no-op and writes nothing, so
        # unconfigured games submit exactly as before.
        challenge = attrs.get('challenge')
        from game.presence import evaluate_presence, resolve_presence
        session = attrs['_team'].session
        resolved = resolve_presence(session, challenge, tower, team=attrs['_team'])
        if not resolved['is_noop']:
            result = evaluate_presence(
                session=session,
                team=attrs['_team'],
                tower=tower,
                submitter=self.context['request'].user,
                submission_point=point,
                resolved=resolved,
                has_photo=bool(attrs.get('photo')),
            )
            if not result.satisfied:
                raise serializers.ValidationError({
                    'detail': result.detail,
                    'presence': {
                        'reason_code': result.reason_code,
                        'required_members': resolved['min_members'],
                        'present_members': result.present_count,
                        'method': resolved['method'],
                    },
                })
            attrs['_presence'] = (resolved, result)

        # team-roles: role-requirement gate. Evaluated on the submitting
        # team's ACTIVE role holders, independent of head-count. A
        # `require_holders_present` challenge defers the presence test to
        # the presence-rules capability (see above); role assignment is
        # checked here.
        if challenge is not None:
            ok, missing = challenge.team_satisfies_roles(attrs['_team'])
            if not ok:
                raise serializers.ValidationError({
                    'detail': (
                        'Echipa nu îndeplinește rolurile cerute de provocare. '
                        f"Roluri lipsă: {', '.join(missing)}."
                    ),
                    'missing_roles': missing,
                })

        # Phase 10: paused-session gating (lifecycle state is the source
        # of truth; equivalent to the open-PauseWindow predicate).
        if session.is_paused():
            if session.effective('pause_rejects_submissions'):
                raise SessionPausedError()
            # Accept but hold — do not capture until the session resumes.
            attrs['_paused_hold'] = True

        # Phase 10: explicit failure lockout on this tower.
        counter = TeamTowerFailCounter.objects.filter(
            team=attrs['_team'], tower=tower,
        ).first()
        if counter and counter.is_locked():
            raise TowerLockedError()

        # mode-trail-discovery: a challenge-less submission at the
        # party's current gate-less trail step is the read-only
        # "acknowledge the clue" gate — arrival within range unlocks it,
        # so it auto-confirms instead of entering staff review.
        trail_ack_step = None
        if handler is None and challenge is None:
            trail_ack_step = read_only_gate_step(
                session, attrs['_team'], user.profile, tower,
            )

        # challenge-type-system: resolve the outcome LAST, so every gate
        # above applies to auto types too. A held submission (paused
        # session, rejects disabled) stays PENDING — capture waits for
        # resume, exactly as the pre-change RFID hold behaved.
        # presence-rules: a photo-fallback submission (hold_for_review)
        # must be reviewed by a human — it never auto-resolves, RFID/scan
        # included, so it takes precedence over the handler outcome.
        presence = attrs.get('_presence')
        if attrs.get('_paused_hold'):
            attrs['_resolved_outcome'] = TeamTowerChallenge.PENDING
        elif presence is not None and presence[1].hold_for_review:
            attrs['_resolved_outcome'] = TeamTowerChallenge.PENDING
        elif handler is not None and effective_mode == REVIEW_AUTO:
            attrs['_resolved_outcome'] = handler.validate(
                challenge, tower, attrs['_team'], submitted_code=submitted_code,
            )
        elif trail_ack_step is not None:
            attrs['_resolved_outcome'] = TeamTowerChallenge.CONFIRMED
        else:
            attrs['_resolved_outcome'] = TeamTowerChallenge.PENDING

        return attrs

    def create(self, validated_data):
        validated_data.pop('lat')
        validated_data.pop('lng')
        validated_data.pop('rfid_code', None)
        validated_data.pop('_handler', None)
        validated_data.pop('_effective_mode', None)
        validated_data.pop('_paused_hold', False)
        team = validated_data.pop('_team')
        # The outcome (CONFIRMED/REJECTED/PENDING) was fully resolved in
        # validate() — it already accounts for the paused hold and the
        # presence photo-fallback hold, so create() only persists it.
        outcome = validated_data.pop('_resolved_outcome')
        presence = validated_data.pop('_presence', None)
        user = self.context['request'].user

        extra = {}
        if outcome != TeamTowerChallenge.PENDING:
            # System-resolved (AUTO) outcome: stamp the verification time
            # now; checked_by stays NULL — the outcome is attributed to
            # the system, not a reviewing staff user.
            extra['timestamp_verified'] = timezone.now()

        ttc = TeamTowerChallenge(
            team=team,
            submitted_by=user,
            outcome=outcome,
            **validated_data,
            **extra,
        )
        if outcome == TeamTowerChallenge.REJECTED:
            # Auto-reject feeds the failure consequences on insert (see
            # TeamTowerChallenge._on_submission_created).
            ttc._system_resolved = True
        ttc.save()
        if presence is not None:
            resolved, result = presence
            PresenceCheck.objects.create(
                team_tower_challenge=ttc,
                required_count=resolved['min_members'],
                present_count=result.present_count,
                method=result.method_used,
                verified_member_ids=result.verified_member_ids,
                window_seconds=resolved['window_seconds'],
                window_satisfied=result.window_satisfied,
                satisfied=result.satisfied,
                reason_code=result.reason_code,
            )
        return ttc
