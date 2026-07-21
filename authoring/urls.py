"""Staff review + credential endpoints for the MCP authoring server."""
from django.urls import path

from . import api

urlpatterns = [
    path(
        'api/staff/authoring/proposals/',
        api.AuthoringProposalListView.as_view(),
        name='authoring-proposal-list',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/',
        api.AuthoringProposalDetailView.as_view(),
        name='authoring-proposal-detail',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/approve/',
        api.AuthoringProposalApproveView.as_view(),
        name='authoring-proposal-approve',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/reject/',
        api.AuthoringProposalRejectView.as_view(),
        name='authoring-proposal-reject',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/apply/',
        api.AuthoringProposalApplyView.as_view(),
        name='authoring-proposal-apply',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/withdraw/',
        api.AuthoringProposalWithdrawView.as_view(),
        name='authoring-proposal-withdraw',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/operations/<int:op_pk>/approve/',
        api.AuthoringOperationDecisionView.as_view(target_status='APPROVED'),
        name='authoring-operation-approve',
    ),
    path(
        'api/staff/authoring/proposals/<int:pk>/operations/<int:op_pk>/reject/',
        api.AuthoringOperationDecisionView.as_view(target_status='REJECTED'),
        name='authoring-operation-reject',
    ),
    path(
        'api/staff/authoring/audit/',
        api.AuthoringAuditListView.as_view(),
        name='authoring-audit-list',
    ),
    path(
        'api/staff/authoring/credentials/',
        api.McpCredentialListCreateView.as_view(),
        name='authoring-credential-list',
    ),
    path(
        'api/staff/authoring/credentials/<int:pk>/revoke/',
        api.McpCredentialRevokeView.as_view(),
        name='authoring-credential-revoke',
    ),
]
