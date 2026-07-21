"""Staff review API: approve/reject/apply proposals + MCP credentials.

These are ordinary staff DRF endpoints — the MCP/LLM path can never
reach them, so approval is always a human action. Apply re-runs as the
*creator* (proposal.created_by), re-checking scope at apply time.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import apply_proposal
from .models import (
    EVENT_DECISION,
    OP_APPROVED,
    OP_PENDING,
    OP_REJECTED,
    PROPOSAL_APPROVED,
    PROPOSAL_DECIDABLE_STATES,
    PROPOSAL_REJECTED,
    PROPOSAL_WITHDRAWN,
    AuthoringAuditEvent,
    AuthoringProposal,
    McpCredential,
    ProposedOperation,
    record_event,
)
from .serializers import (
    AuthoringAuditEventSerializer,
    AuthoringProposalDetailSerializer,
    AuthoringProposalListSerializer,
    McpCredentialSerializer,
)


def _can_review(user, proposal):
    """A human decision requires the creator or a superuser."""
    return user.is_superuser or proposal.created_by_id == user.id


def _reviewable_proposals(user):
    qs = AuthoringProposal.objects.select_related('session', 'created_by')
    if user.is_superuser:
        return qs
    return qs.filter(created_by=user)


class AuthoringProposalListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = _reviewable_proposals(request.user).order_by('-created_at')
        state = request.query_params.get('status')
        if state:
            qs = qs.filter(status=state)
        return Response(AuthoringProposalListSerializer(qs, many=True).data)


class AuthoringProposalDetailView(APIView):
    permission_classes = [IsAdminUser]

    def _get(self, request, pk):
        proposal = get_object_or_404(AuthoringProposal, pk=pk)
        if not _can_review(request.user, proposal):
            return None
        return proposal

    def get(self, request, pk):
        proposal = self._get(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(AuthoringProposalDetailSerializer(proposal).data)


class _ProposalActionView(APIView):
    permission_classes = [IsAdminUser]

    def _load(self, request, pk):
        proposal = get_object_or_404(AuthoringProposal, pk=pk)
        if not _can_review(request.user, proposal):
            return None
        return proposal


class AuthoringProposalApproveView(_ProposalActionView):
    def post(self, request, pk):
        proposal = self._load(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if proposal.status not in PROPOSAL_DECIDABLE_STATES:
            return Response(
                {'detail': f'Cannot approve a {proposal.status} proposal.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Approve every operation not explicitly rejected.
        proposal.operations.exclude(status=OP_REJECTED).update(status=OP_APPROVED)
        proposal.status = PROPOSAL_APPROVED
        proposal.decided_by = request.user
        proposal.decided_at = timezone.now()
        proposal.save(update_fields=['status', 'decided_by', 'decided_at', 'updated_at'])
        record_event(
            EVENT_DECISION, created_by=request.user, session=proposal.session,
            proposal=proposal, tool_name='approve', result={'status': PROPOSAL_APPROVED},
        )
        return Response(AuthoringProposalDetailSerializer(proposal).data)


class AuthoringProposalRejectView(_ProposalActionView):
    def post(self, request, pk):
        proposal = self._load(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if proposal.status not in PROPOSAL_DECIDABLE_STATES:
            return Response(
                {'detail': f'Cannot reject a {proposal.status} proposal.'},
                status=status.HTTP_409_CONFLICT,
            )
        proposal.operations.exclude(status='APPLIED').update(status=OP_REJECTED)
        proposal.status = PROPOSAL_REJECTED
        proposal.decided_by = request.user
        proposal.decided_at = timezone.now()
        proposal.save(update_fields=['status', 'decided_by', 'decided_at', 'updated_at'])
        record_event(
            EVENT_DECISION, created_by=request.user, session=proposal.session,
            proposal=proposal, tool_name='reject', result={'status': PROPOSAL_REJECTED},
        )
        return Response(AuthoringProposalDetailSerializer(proposal).data)


class AuthoringProposalWithdrawView(_ProposalActionView):
    def post(self, request, pk):
        proposal = self._load(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        proposal.status = PROPOSAL_WITHDRAWN
        proposal.save(update_fields=['status', 'updated_at'])
        record_event(
            EVENT_DECISION, created_by=request.user, session=proposal.session,
            proposal=proposal, tool_name='withdraw', result={'status': PROPOSAL_WITHDRAWN},
        )
        return Response(AuthoringProposalListSerializer(proposal).data)


class AuthoringProposalApplyView(_ProposalActionView):
    def post(self, request, pk):
        proposal = self._load(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if proposal.status != PROPOSAL_APPROVED:
            return Response(
                {'detail': 'Only an APPROVED proposal can be applied.'},
                status=status.HTTP_409_CONFLICT,
            )
        if not proposal.operations.filter(status=OP_APPROVED).exists():
            return Response(
                {'detail': 'No approved operations to apply.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Apply runs as the creator so scope is re-checked against the
        # authoring identity, not the reviewer's.
        apply_proposal(proposal, actor=proposal.created_by)
        proposal.refresh_from_db()
        return Response(AuthoringProposalDetailSerializer(proposal).data)


class AuthoringOperationDecisionView(_ProposalActionView):
    """Per-operation approve/reject before a whole-proposal decision."""

    target_status = None

    def post(self, request, pk, op_pk):
        proposal = self._load(request, pk)
        if proposal is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        op = get_object_or_404(ProposedOperation, pk=op_pk, proposal=proposal)
        if op.status not in (OP_PENDING, OP_APPROVED, OP_REJECTED):
            return Response(
                {'detail': f'Operation is {op.status}; cannot change.'},
                status=status.HTTP_409_CONFLICT,
            )
        op.status = self.target_status
        op.save(update_fields=['status'])
        record_event(
            EVENT_DECISION, created_by=request.user, session=proposal.session,
            proposal=proposal, tool_name='operation_decision',
            args={'operation': op.id}, result={'status': self.target_status},
        )
        return Response(AuthoringProposalDetailSerializer(proposal).data)


class AuthoringAuditListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = AuthoringAuditEvent.objects.select_related('created_by').all()
        if not request.user.is_superuser:
            qs = qs.filter(created_by=request.user)
        for key in ('proposal', 'session'):
            value = request.query_params.get(key)
            if value:
                qs = qs.filter(**{f'{key}_id': value})
        return Response(AuthoringAuditEventSerializer(qs[:500], many=True).data)


class McpCredentialListCreateView(APIView):
    """Issue (POST, returns the raw token once) and list (GET) credentials."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = McpCredential.objects.filter(created_by=request.user)
        return Response(McpCredentialSerializer(qs, many=True).data)

    def post(self, request):
        label = request.data.get('label', '')
        credential, raw_token = McpCredential.issue(request.user, label=label)
        data = McpCredentialSerializer(credential).data
        # The raw token is shown exactly once.
        data['token'] = raw_token
        return Response(data, status=status.HTTP_201_CREATED)


class McpCredentialRevokeView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        credential = get_object_or_404(McpCredential, pk=pk, created_by=request.user)
        credential.revoke()
        return Response(McpCredentialSerializer(credential).data)
