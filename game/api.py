from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import Challenge, TeamTowerChallenge, Tower

COOLOFF_MINUTES = 5


class ChallengeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Challenge
        fields = ('id', 'text', 'difficulty', 'tower')


class OwnershipSummarySerializer(serializers.Serializer):
    team_id = serializers.IntegerField()
    team_name = serializers.CharField()
    team_color = serializers.CharField()


class TowerStateView(APIView):
    """Player-facing state for a specific tower.

    Scopes next-challenge, pending, and cooloff to the caller's active
    team. Staff without an active team get a 404 — the view is meant for
    the active-team, tower-detail player flow.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tower = get_object_or_404(Tower, pk=pk, is_active=True)
        membership = (
            request.user.profile.memberships
            .filter(is_active=True)
            .select_related('team')
            .first()
        )
        if membership is None:
            return Response(
                {'detail': 'You are not a member of any team.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team = membership.team

        last_rejected = (
            TeamTowerChallenge.objects
            .filter(team=team, tower=tower, outcome=TeamTowerChallenge.REJECTED)
            .order_by('-timestamp_verified')
            .first()
        )
        cooloff_until = None
        if last_rejected and last_rejected.timestamp_verified:
            candidate = last_rejected.timestamp_verified + timedelta(
                minutes=COOLOFF_MINUTES,
            )
            if candidate > timezone.now():
                cooloff_until = candidate

        pending = TeamTowerChallenge.objects.filter(
            team=team, tower=tower, outcome=TeamTowerChallenge.PENDING,
        ).exists()

        next_challenge = tower.get_next_challenge(team) if not pending else None

        ownership = tower.tower_control(team.group) if team.group else None
        ownership_payload = None
        if ownership is not None:
            ownership_payload = {
                'team_id': ownership.id,
                'team_name': ownership.name,
                'team_color': ownership.color,
            }

        return Response({
            'id': tower.id,
            'name': tower.name,
            'category': tower.category,
            'location': {
                'type': 'Point',
                'coordinates': [tower.location.x, tower.location.y],
            },
            'has_initial_bonus': tower.initial_bonus != 0,
            'ownership': ownership_payload,
            'next_challenge': (
                ChallengeSummarySerializer(next_challenge).data
                if next_challenge else None
            ),
            'pending_submission': pending,
            'cooloff_until': (
                cooloff_until.isoformat() if cooloff_until else None
            ),
            'proximity_meters': 50,
        })
