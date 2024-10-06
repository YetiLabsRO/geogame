from rest_framework import serializers

from game.models import Zone, Tower, Team, Challenge, TeamTowerChallenge
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance


class ZoneSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Zone
        fields = ["name", "color", "scoring_type", "shape", "team_color"]

    team_color = serializers.SerializerMethodField()

    def get_team_color(self, zone):
        category = int(self.context.get("category", 0))
        if category:
            control_team_ids = zone.zone_control(category=category)
            teams = Team.objects.filter(pk__in=control_team_ids)
            if teams.count() > 1:
                return "#FFFFFF"
            elif teams.count() == 1:
                return teams.first().color
        return "#000000"


class TowerSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Tower
        fields = ["name", "location", "zone", "category", "is_active", "ownership", "id"]

    ownership = serializers.SerializerMethodField()

    def get_ownership(self, obj):
        #   TODO: fix this
        return TeamSerializer(obj.tower_control(1)).data


class TeamSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Team
        fields = ["name", "code", "category", "current_score", "color"]


class ChallengeSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Challenge
        fields = ["text", "tower", "difficulty"]


class Base64ImageField(serializers.ImageField):

    def to_internal_value(self, data):
        from django.core.files.base import ContentFile
        import base64
        import uuid

        if isinstance(data, str):
            if 'data:' in data and ';base64,' in data:
                header, data = data.split(';base64,')

            try:
                decoded_file = base64.b64decode(data)
            except TypeError:
                self.fail('invalid_image')

            file_name = str(uuid.uuid4())[:12] # 12 characters are more than enough.
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
    class Meta:
        model = TeamTowerChallenge
        fields = ["photo", "team", "challenge", "tower", "lng", "lat", "response_text"]

    photo = Base64ImageField(max_length=None, use_url=True, required=False, allow_empty_file=True, allow_null=True)
    lat = serializers.FloatField(required=True, write_only=True)
    lng = serializers.FloatField(required=True, write_only=True)

    def validate(self, attrs):
        if not attrs['lat'] or not attrs['lng']:
            raise serializers.ValidationError("Dacă nu ești la turn, nu poți face provocarea!")

        if not attrs['tower']:
            raise serializers.ValidationError("Trebuie un turn!")

        point = Point(attrs['lng'], attrs['lat'])
        try:
            Tower.objects.filter(pk=attrs['tower'].id, location__distance_lt=(point, Distance(m=50)))
        except Tower.DoesNotExist:
            raise serializers.ValidationError("Trebuie să fii la maxim 50 de metri de turn pentru a putea face provoarea!")

        return attrs

    def create(self, validated_data):
        validated_data.pop("lat")
        validated_data.pop("lng")
        return super(TeamTowerChallengeSerializer, self).create(validated_data)
