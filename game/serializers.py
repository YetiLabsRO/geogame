from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from rest_framework import serializers

from game.models import Challenge, TeamTowerChallenge, Tower, Zone
from organize.models import Team


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

    class Meta:
        model = Team
        fields = [
            "id", "name", "code", "group", "group_name", "group_slug",
            "current_score", "color",
        ]


class ChallengeSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Challenge
        fields = ["text", "tower", "difficulty"]


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
        if not Tower.objects.filter(
            pk=tower.id,
            location__distance_lte=(point, Distance(m=50)),
        ).exists():
            raise serializers.ValidationError(
                "Trebuie să fii la maxim 50 de metri de turn pentru a putea face provocarea!",
            )

        return attrs

    def create(self, validated_data):
        validated_data.pop('lat')
        validated_data.pop('lng')
        validated_data.pop('rfid_code', None)
        team = validated_data.pop('_team')
        auto_confirm = validated_data.pop('_auto_confirm')
        user = self.context['request'].user

        ttc = TeamTowerChallenge.objects.create(
            team=team,
            submitted_by=user,
            outcome=TeamTowerChallenge.CONFIRMED if auto_confirm else TeamTowerChallenge.PENDING,
            **validated_data,
        )
        return ttc
