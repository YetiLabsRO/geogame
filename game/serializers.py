from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from rest_framework import serializers
from rest_framework.exceptions import APIException

from game.models import (
    Challenge,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    Tower,
    Zone,
)
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
        fields = ["name", "color", "scoring_type", "shape", "team_color"]

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
        fields = ["name", "location", "zone", "category", "is_active", "ownership", "id", "has_initial_bonus"]

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
    required_role_slugs = serializers.SerializerMethodField()

    class Meta:
        model = Challenge
        fields = ["text", "tower", "difficulty", "role_requirement_mode", "required_role_slugs"]

    def get_required_role_slugs(self, challenge):
        return [role.slug for role in challenge.required_roles.all()]


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
    active RFID tower and marks the submission CONFIRMED.

    Check order: membership → tower/RFID resolution → GPS proximity →
    challenge role requirement (team-roles) → paused session → failure
    lockout. The role gate runs after proximity so "you are too far" wins
    over "you lack a role", and before the pause/lockout state checks.
    """

    class Meta:
        model = TeamTowerChallenge
        fields = [
            "id",
            "photo",
            "challenge",
            "tower",
            "rfid_code",
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

        rfid_code = attrs.get('rfid_code') or None
        tower = attrs.get('tower')

        if rfid_code:
            try:
                tower = Tower.objects.get(
                    rfid_code=rfid_code,
                    is_active=True,
                    category=Tower.CATEGORY_RFID,
                )
            except Tower.DoesNotExist:
                raise serializers.ValidationError("Cod RFID necunoscut sau turn inactiv.")
            attrs['tower'] = tower
            attrs['_auto_confirm'] = True
        else:
            if not tower:
                raise serializers.ValidationError("Trebuie un turn sau un cod RFID.")
            attrs['_auto_confirm'] = False

        if not attrs.get('lat') or not attrs.get('lng'):
            raise serializers.ValidationError("Dacă nu ești la turn, nu poți face provocarea!")

        point = Point(attrs['lng'], attrs['lat'])
        proximity = tower.game.proximity_meters
        if not Tower.objects.filter(
            pk=tower.id,
            location__distance_lte=(point, Distance(m=proximity)),
        ).exists():
            raise serializers.ValidationError(
                f"Trebuie să fii la maxim {proximity} de metri de turn "
                "pentru a putea face provocarea!",
            )

        # team-roles: role-requirement gate. Evaluated on the submitting
        # team's ACTIVE role holders, independent of head-count. A
        # `require_holders_present` challenge defers the presence test to
        # the presence-rules capability; until that ships, assignment
        # alone suffices (the default path).
        challenge = attrs.get('challenge')
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
        session = attrs['_team'].session
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

        return attrs

    def create(self, validated_data):
        validated_data.pop('lat')
        validated_data.pop('lng')
        validated_data.pop('rfid_code', None)
        team = validated_data.pop('_team')
        auto_confirm = validated_data.pop('_auto_confirm')
        paused_hold = validated_data.pop('_paused_hold', False)
        user = self.context['request'].user

        # A held submission (paused session, rejects disabled) is stored
        # PENDING and never auto-confirms — capture waits for resume.
        if paused_hold:
            auto_confirm = False

        ttc = TeamTowerChallenge.objects.create(
            team=team,
            submitted_by=user,
            outcome=TeamTowerChallenge.CONFIRMED if auto_confirm else TeamTowerChallenge.PENDING,
            **validated_data,
        )
        return ttc
