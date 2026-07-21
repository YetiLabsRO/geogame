from django.urls import path

from organize import api

urlpatterns = [
    path('auth/register/', api.register, name='api-auth-register'),
    path('auth/login/', api.login, name='api-auth-login'),
    path('auth/logout/', api.logout, name='api-auth-logout'),
    path('auth/password-reset/', api.password_reset_request, name='api-password-reset'),
    path('auth/password-reset/confirm/', api.password_reset_confirm, name='api-password-reset-confirm'),
    path('me/', api.MeView.as_view(), name='api-me'),
    path('my-team/', api.MyTeamView.as_view(), name='api-my-team'),
    path('current-session/', api.CurrentSessionView.as_view(), name='api-current-session'),
    path('my-sessions/', api.MySessionsView.as_view(), name='api-my-sessions'),
    path(
        'sessions/<int:pk>/scoreboard/',
        api.SessionScoreboardView.as_view(),
        name='api-session-scoreboard',
    ),
    path(
        'sessions/<int:pk>/timeline/',
        api.SessionTimelineView.as_view(),
        name='api-session-timeline',
    ),
    path('invites/', api.InviteListCreate.as_view(), name='api-invites'),
    path('invites/accept/<uuid:token>/', api.invite_accept, name='api-invite-accept'),
    path('invites/<uuid:token>/', api.invite_preview, name='api-invite-preview'),
    path('invites/<int:pk>/', api.InviteDestroy.as_view(), name='api-invite-destroy'),
    path('invites/<int:pk>/resend/', api.invite_resend, name='api-invite-resend'),
    # Team formation (player-team-formation change). The teams/<pk>/…
    # route intentionally lives here: the DRF router registered at
    # api/teams/ never matches the extra /join-code/ suffix, so URL
    # resolution falls through to this include.
    path(
        'teams/<int:pk>/join-code/',
        api.TeamJoinCodeView.as_view(),
        name='api-team-join-code',
    ),
    path(
        'join-codes/<uuid:code>/',
        api.join_code_preview,
        name='api-join-code-preview',
    ),
    path('joinable-teams/', api.JoinableTeamsView.as_view(), name='api-joinable-teams'),
    path(
        'join-requests/',
        api.JoinRequestListCreateView.as_view(),
        name='api-join-requests',
    ),
    path(
        'join-requests/<int:pk>/approve/',
        api.join_request_approve,
        name='api-join-request-approve',
    ),
    path(
        'join-requests/<int:pk>/reject/',
        api.join_request_reject,
        name='api-join-request-reject',
    ),
]
