from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
    Challenge,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from organize.models import Team, TeamGroup


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
            'code', 'group', 'color', 'description',
        )


class AdminTeamGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamGroup
        fields = ('id', 'name', 'game', 'slug')


class AdminChallengeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Challenge
        fields = ('id', 'game', 'text', 'tower', 'difficulty')


class AdminZoneViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Zones. Shape editing stays in Django admin."""

    permission_classes = [IsAdminUser]
    queryset = Zone.objects.all().order_by('name')
    serializer_class = AdminZoneSerializer


class AdminTowerViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Towers + activate/deactivate/unassign actions.

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
        towers = list(Tower.objects.filter(is_active=True))
        for tower in towers:
            tower.unassign()
        return Response(
            {'unassigned': [t.id for t in towers]},
            status=status.HTTP_200_OK,
        )


class AdminTeamViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Teams."""

    permission_classes = [IsAdminUser]
    queryset = Team.objects.all().order_by('name')
    serializer_class = AdminTeamSerializer


class AdminTeamGroupList(viewsets.ReadOnlyModelViewSet):
    """Staff-only read access to TeamGroups (needed by the team edit form)."""

    permission_classes = [IsAdminUser]
    queryset = TeamGroup.objects.all().order_by('name')
    serializer_class = AdminTeamGroupSerializer


class AdminChallengeViewSet(viewsets.ModelViewSet):
    """Staff-only CRUD for Challenges (tower-specific or generic)."""

    permission_classes = [IsAdminUser]
    queryset = Challenge.objects.all().order_by('difficulty', 'id')
    serializer_class = AdminChallengeSerializer


class ResetScoresView(APIView):
    """Staff-only: zero out all Team.score and close every open ownership.

    Intended as a "start a fresh round" button. Distinct from
    unassign_all (which just closes current tower ownerships) in that
    this also resets the locked, cumulative Team.score to 0.
    """

    permission_classes = [IsAdminUser]

    @transaction.atomic
    def post(self, request):
        from django.utils import timezone
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
