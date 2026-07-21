from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import (
    ROLE_REQUIREMENT_NONE,
    Challenge,
    TeamTowerChallenge,
    Tower,
)
from game.scoping import SessionScopedViewSetMixin


class ChallengeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Challenge
        fields = ('id', 'text', 'difficulty', 'tower')


class OwnershipSummarySerializer(serializers.Serializer):
    team_id = serializers.IntegerField()
    team_name = serializers.CharField()
    team_color = serializers.CharField()


def _role_requirement_payload(challenge, team):
    """Player-facing role requirement + satisfaction hint (team-roles).

    None when the challenge declares no requirement (the default), so
    pre-change clients see no behavior change.
    """
    if challenge is None or challenge.role_requirement_mode == ROLE_REQUIREMENT_NONE:
        return None
    ok, missing = challenge.team_satisfies_roles(team)
    return {
        'mode': challenge.role_requirement_mode,
        'required_roles': [
            {'slug': role.slug, 'name': role.name}
            for role in challenge.required_roles.all()
        ],
        'require_holders_present': challenge.require_holders_present,
        'team_satisfies': ok,
        'missing_roles': missing,
    }


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
            # Rule config comes from the team's Game (via its Session) —
            # repository towers have no single owning Game.
            candidate = last_rejected.timestamp_verified + timedelta(
                minutes=team.session.game.cooloff_minutes,
            )
            if candidate > timezone.now():
                cooloff_until = candidate

        pending = TeamTowerChallenge.objects.filter(
            team=team, tower=tower, outcome=TeamTowerChallenge.PENDING,
        ).exists()

        next_challenge = tower.get_next_challenge(team) if not pending else None
        next_challenge_payload = None
        if next_challenge is not None:
            next_challenge_payload = ChallengeSummarySerializer(next_challenge).data
            next_challenge_payload['role_requirement'] = _role_requirement_payload(
                next_challenge, team,
            )

        # presence-rules: required-vs-present status for the challenge at
        # this tower. None on the default no-op resolution, so pre-change
        # clients see no payload change. Re-fetching this endpoint updates
        # the count as teammates enter/leave the geofence.
        from game.presence import presence_status_payload
        presence = presence_status_payload(
            team.session, team, tower, next_challenge,
        )

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
            'next_challenge': next_challenge_payload,
            'presence': presence,
            'pending_submission': pending,
            'cooloff_until': (
                cooloff_until.isoformat() if cooloff_until else None
            ),
            'proximity_meters': team.session.game.proximity_meters,
        })


# ---------------------------------------------------------------------------
# Staff submission review
# ---------------------------------------------------------------------------


class StaffSubmissionSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    team_color = serializers.CharField(source='team.color', read_only=True)
    tower_name = serializers.CharField(source='tower.name', read_only=True)
    challenge_text = serializers.SerializerMethodField()
    challenge_difficulty = serializers.SerializerMethodField()
    submitted_by_username = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    presence_check = serializers.SerializerMethodField()

    class Meta:
        model = TeamTowerChallenge
        fields = (
            'id', 'team', 'team_name', 'team_color',
            'tower', 'tower_name',
            'challenge', 'challenge_text', 'challenge_difficulty',
            'submitted_by', 'submitted_by_username',
            'photo_url', 'timestamp_submitted', 'timestamp_verified',
            'outcome', 'response_text', 'presence_check',
        )

    def get_presence_check(self, obj):
        """Presence evidence (presence-rules): None for ungated submissions."""
        check = getattr(obj, 'presence_check', None)
        if check is None:
            return None
        return {
            'required_count': check.required_count,
            'present_count': check.present_count,
            'method': check.method,
            'verified_member_ids': check.verified_member_ids,
            'window_seconds': check.window_seconds,
            'window_satisfied': check.window_satisfied,
            'satisfied': check.satisfied,
            'reason_code': check.reason_code,
        }

    def get_challenge_text(self, obj):
        return obj.challenge.text if obj.challenge else None

    def get_challenge_difficulty(self, obj):
        return obj.challenge.difficulty if obj.challenge else None

    def get_submitted_by_username(self, obj):
        return obj.submitted_by.username if obj.submitted_by else None

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        request = self.context.get('request')
        url = obj.photo.url
        return request.build_absolute_uri(url) if request else url


class StaffSubmissionList(SessionScopedViewSetMixin, generics.ListAPIView):
    """Staff-only: list submissions, filterable by outcome.

    Default scope is PENDING submissions so the review queue is the
    default experience; pass ?outcome=all or a specific integer outcome
    to see others.
    """

    permission_classes = [IsAdminUser]
    serializer_class = StaffSubmissionSerializer
    session_scope_field = 'team__session'
    queryset = (
        TeamTowerChallenge.objects
        .select_related(
            'team', 'tower', 'challenge', 'submitted_by', 'presence_check',
        )
        .order_by('-timestamp_submitted')
    )

    def get_queryset(self):
        qs = super().get_queryset()
        outcome = self.request.query_params.get('outcome', 'pending')
        if outcome == 'all':
            return qs
        if outcome == 'pending':
            return qs.filter(outcome=TeamTowerChallenge.PENDING)
        if outcome == 'confirmed':
            return qs.filter(outcome=TeamTowerChallenge.CONFIRMED)
        if outcome == 'rejected':
            return qs.filter(outcome=TeamTowerChallenge.REJECTED)
        return qs.filter(outcome=TeamTowerChallenge.PENDING)


class StaffSubmissionReview(APIView):
    """Staff-only: confirm or reject a pending submission.

    Accepts {"outcome": "confirm"|"reject", "response_text": "..."}.
    Sets checked_by to the reviewing staff user. Confirming triggers
    the model's tower-assignment side-effects via TTC.save().
    """

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        submission = get_object_or_404(TeamTowerChallenge, pk=pk)
        if submission.outcome != TeamTowerChallenge.PENDING:
            return Response(
                {'detail': 'Submission is not pending.'},
                status=status.HTTP_409_CONFLICT,
            )
        outcome_str = request.data.get('outcome')
        if outcome_str == 'confirm':
            submission.outcome = TeamTowerChallenge.CONFIRMED
        elif outcome_str == 'reject':
            submission.outcome = TeamTowerChallenge.REJECTED
            submission.response_text = request.data.get('response_text', '')
        else:
            return Response(
                {'detail': 'outcome must be "confirm" or "reject".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        submission.checked_by = request.user
        submission.save()
        return Response(
            StaffSubmissionSerializer(
                submission, context={'request': request},
            ).data,
        )
