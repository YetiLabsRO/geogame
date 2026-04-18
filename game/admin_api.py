from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from game.models import Tower, Zone
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
    class Meta:
        model = Team
        fields = ('id', 'name', 'game', 'code', 'group', 'color', 'description')


class AdminTeamGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamGroup
        fields = ('id', 'name', 'game', 'slug')


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
