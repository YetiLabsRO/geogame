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
    path('invites/', api.InviteListCreate.as_view(), name='api-invites'),
    path('invites/accept/<uuid:token>/', api.invite_accept, name='api-invite-accept'),
    path('invites/<uuid:token>/', api.invite_preview, name='api-invite-preview'),
    path('invites/<int:pk>/', api.InviteDestroy.as_view(), name='api-invite-destroy'),
    path('invites/<int:pk>/resend/', api.invite_resend, name='api-invite-resend'),
]
