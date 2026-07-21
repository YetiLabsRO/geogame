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
    TowerLock,
)
from game.scoping import SessionScopedViewSetMixin
from organize.models import TOWER_LOCK_ON_INITIATE


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


def _active_membership(request):
    """The caller's active TeamMembership (with team), or None."""
    return (
        request.user.profile.memberships
        .filter(is_active=True)
        .select_related('team')
        .first()
    )


def _lock_payload(lock, team, now=None):
    """Player-facing view of an active lock (tower-locking § visibility).

    None when there is no active lock. `held_by_us` drives the
    locked-by-us / locked-by-others distinction; `expires_at` +
    `remaining_seconds` drive the finish-deadline countdown.
    """
    if lock is None:
        return None
    now = now or timezone.now()
    return {
        'held_by_us': lock.team_id == team.id,
        'team_id': lock.team_id,
        'team_name': lock.team.name,
        'team_color': lock.team.color,
        'started_at': lock.started_at.isoformat(),
        'expires_at': lock.expires_at.isoformat(),
        'remaining_seconds': lock.remaining_seconds(now),
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
        membership = _active_membership(request)
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

        ownership = tower.tower_control(team.group) if team.group else None
        ownership_payload = None
        if ownership is not None:
            ownership_payload = {
                'team_id': ownership.id,
                'team_name': ownership.name,
                'team_color': ownership.color,
            }

        # tower-locking: effective mode + the group's active lock (if
        # any) so the client can render locked-by-us / locked-by-others /
        # free and the finish-deadline countdown.
        lock_mode = team.session.effective('tower_lock_mode')
        lock = tower.active_lock(team.group)

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
            'pending_submission': pending,
            'cooloff_until': (
                cooloff_until.isoformat() if cooloff_until else None
            ),
            'proximity_meters': team.session.game.proximity_meters,
            'tower_lock_mode': lock_mode,
            'lock': _lock_payload(lock, team),
        })


# ---------------------------------------------------------------------------
# tower-locking: identify → initiate lifecycle endpoints
# ---------------------------------------------------------------------------


class TowerIdentifyView(APIView):
    """POST /api/towers/{id}/identify/ — the IDENTIFY lifecycle phase.

    Serves the caller team's next challenge via `get_next_challenge`
    with no side effects: identifying never commits the team, never
    touches any lock, and is safe to repeat.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tower = get_object_or_404(Tower, pk=pk, is_active=True)
        membership = _active_membership(request)
        if membership is None:
            return Response(
                {'detail': 'You are not a member of any team.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team = membership.team
        challenge = tower.get_next_challenge(team)
        payload = None
        if challenge is not None:
            payload = ChallengeSummarySerializer(challenge).data
            payload['role_requirement'] = _role_requirement_payload(challenge, team)
        return Response({
            'id': tower.id,
            'tower_lock_mode': team.session.effective('tower_lock_mode'),
            'next_challenge': payload,
            'lock': _lock_payload(tower.active_lock(team.group), team),
        })


class TowerInitiateView(APIView):
    """POST /api/towers/{id}/initiate/ — the INITIATE lifecycle phase.

    Under LOCK_ON_INITIATE this is the commitment point: it acquires a
    TowerLock for the caller team's group (409 when another team in the
    group holds the active lock). Under FREE_FOR_ALL it is a side-effect
    -free acknowledgement so pre-locking clients keep working unchanged.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tower = get_object_or_404(Tower, pk=pk, is_active=True)
        membership = _active_membership(request)
        if membership is None:
            return Response(
                {'detail': 'You are not a member of any team.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team = membership.team
        mode = team.session.effective('tower_lock_mode')
        if mode != TOWER_LOCK_ON_INITIATE:
            return Response({
                'tower_lock_mode': mode,
                'locked': False,
                'lock': None,
            })
        if team.group_id is None:
            return Response(
                {'detail': 'Your team has no group; locks are scoped per team group.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        minutes = team.session.effective('tower_lock_finish_minutes')
        lock, created = TowerLock.acquire(tower, team, minutes)
        if lock is None:
            holder = tower.active_lock(team.group)
            return Response(
                {
                    'detail': 'Turnul este blocat de altă echipă.',
                    'lock': _lock_payload(holder, team),
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                'tower_lock_mode': mode,
                'locked': True,
                'lock': _lock_payload(lock, team),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TowerLockReleaseView(APIView):
    """POST /api/towers/{id}/release_lock/ — voluntary CANCELLED release.

    The lock-holding team may give up its own active lock early, freeing
    the tower for the rest of its group before the deadline (§3.5).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tower = get_object_or_404(Tower, pk=pk, is_active=True)
        membership = _active_membership(request)
        if membership is None:
            return Response(
                {'detail': 'You are not a member of any team.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team = membership.team
        lock = tower.active_lock(team.group)
        if lock is None or lock.team_id != team.id:
            return Response(
                {'detail': 'Your team holds no active lock on this tower.'},
                status=status.HTTP_409_CONFLICT,
            )
        lock.release(TowerLock.CANCELLED)
        return Response({'released': True})


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

    class Meta:
        model = TeamTowerChallenge
        fields = (
            'id', 'team', 'team_name', 'team_color',
            'tower', 'tower_name',
            'challenge', 'challenge_text', 'challenge_difficulty',
            'submitted_by', 'submitted_by_username',
            'photo_url', 'timestamp_submitted', 'timestamp_verified',
            'outcome', 'response_text',
        )

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
        .select_related('team', 'tower', 'challenge', 'submitted_by')
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
            # tower-locking: defense against a stale attempt — while an
            # active lock is held by ANOTHER team in the submitter's
            # group under LOCK_ON_INITIATE, that team's finish cannot be
            # confirmed (the capture belongs to the lock holder).
            team = submission.team
            if team.session.effective('tower_lock_mode') == TOWER_LOCK_ON_INITIATE:
                lock = submission.tower.active_lock(team.group)
                if lock is not None and lock.team_id != team.id:
                    return Response(
                        {
                            'detail': (
                                'The tower is locked to another team; '
                                'this finish cannot be confirmed while the lock is active.'
                            ),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
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
