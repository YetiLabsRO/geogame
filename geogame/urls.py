"""geogame URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from game.admin_api import (
    AdminChallengeViewSet,
    AdminCollectionViewSet,
    AdminGameRoleViewSet,
    AdminGameViewSet,
    AdminNfcTagViewSet,
    AdminPresenceRequirementViewSet,
    AdminSessionViewSet,
    AdminTeamGroupList,
    AdminTeamMembershipViewSet,
    AdminTeamViewSet,
    AdminTowerViewSet,
    AdminZoneViewSet,
    ResetScoresView,
    StaffTowerLockViewSet,
)
from game.api import (
    StaffSubmissionList,
    StaffSubmissionReview,
    TowerIdentifyView,
    TowerInitiateView,
    TowerLockReleaseView,
    TowerStateView,
)
from game.badge_api import (
    GatewayIngestView,
    StaffBadgeAssignView,
    StaffBadgeCollectView,
    StaffBadgeListView,
    StaffGatewayListView,
)
from game.location_api import (
    LocationConsentView,
    LocationLiveView,
    LocationPingView,
    StaffLocationHistoryView,
)
from game.multipliers_api import (
    GameScoreMultiplierDetail,
    GameScoreMultiplierListCreate,
    SessionActiveMultipliersView,
    SessionScoreMultiplierListCreate,
    SessionScoreMultiplierToggle,
)
from game.proximity_api import (
    DementorMeView,
    ProximityCapabilityView,
    ProximityIdentityView,
    ProximityReportView,
    StaffDementorTotalsView,
)
from game.trail_api import (
    AdminTrailEdgeViewSet,
    AdminTrailStepViewSet,
    AdminTrailViewSet,
    SessionTrailLeaderboardView,
    SessionTrailRevealStartView,
    SessionTrailRoutesGenerateView,
    SessionTrailRoutesView,
    TrailLeaderboardView,
    TrailNextView,
    TrailStateView,
)
from game.views import (
    ChallengeViewSet,
    NfcCaptureView,
    TeamTowerChallengeViewSet,
    TeamViewSet,
    TowerViewSet,
    ZoneViewSet,
    health,
    nfc_landing,
)

router = routers.DefaultRouter()
router.register(r'zones', ZoneViewSet)
router.register(r'towers', TowerViewSet)
router.register(r'teams', TeamViewSet)
router.register(r'challenges', ChallengeViewSet)
router.register(r'team_tower_challenges', TeamTowerChallengeViewSet)

admin_router = routers.DefaultRouter()
admin_router.register(r'zones', AdminZoneViewSet, basename='admin-zone')
admin_router.register(r'towers', AdminTowerViewSet, basename='admin-tower')
admin_router.register(r'teams', AdminTeamViewSet, basename='admin-team')
admin_router.register(
    r'team-groups', AdminTeamGroupList, basename='admin-team-group',
)
admin_router.register(
    r'challenges', AdminChallengeViewSet, basename='admin-challenge',
)
admin_router.register(
    r'collections', AdminCollectionViewSet, basename='admin-collection',
)
admin_router.register(r'games', AdminGameViewSet, basename='admin-game')
admin_router.register(
    r'game_roles', AdminGameRoleViewSet, basename='admin-game-role',
)
admin_router.register(
    r'memberships', AdminTeamMembershipViewSet, basename='admin-membership',
)
admin_router.register(
    r'sessions', AdminSessionViewSet, basename='admin-session',
)
admin_router.register(
    r'presence-requirements',
    AdminPresenceRequirementViewSet,
    basename='admin-presence-requirement',
)
admin_router.register(
    r'nfc-tags', AdminNfcTagViewSet, basename='admin-nfc-tag',
)
admin_router.register(r'trails', AdminTrailViewSet, basename='admin-trail')
admin_router.register(
    r'trail-steps', AdminTrailStepViewSet, basename='admin-trail-step',
)
admin_router.register(
    r'trail-edges', AdminTrailEdgeViewSet, basename='admin-trail-edge',
)
admin_router.register(
    r'tower_locks', StaffTowerLockViewSet, basename='admin-tower-lock',
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health, name="health"),
    # nfc-native-and-secure-links: browser fallback page (no capture side
    # effect) + the authenticated in-app capture boundary.
    path('nfc/<str:token>/', nfc_landing, name='nfc-landing'),
    path('api/nfc/capture/', NfcCaptureView.as_view(), name='api-nfc-capture'),
    path('api/', include(router.urls)),
    path('api/towers/<int:pk>/state/', TowerStateView.as_view(), name='api-tower-state'),
    # Live-location (live-location capability).
    path('api/location/ping/', LocationPingView.as_view(), name='api-location-ping'),
    path('api/location/live/', LocationLiveView.as_view(), name='api-location-live'),
    path(
        'api/location/consent/',
        LocationConsentView.as_view(),
        name='api-location-consent',
    ),
    path(
        'api/staff/sessions/<int:pk>/location-history/',
        StaffLocationHistoryView.as_view(),
        name='api-staff-location-history',
    ),
    path(
        'api/towers/<int:pk>/identify/',
        TowerIdentifyView.as_view(),
        name='api-tower-identify',
    ),
    path(
        'api/towers/<int:pk>/initiate/',
        TowerInitiateView.as_view(),
        name='api-tower-initiate',
    ),
    path(
        'api/towers/<int:pk>/release_lock/',
        TowerLockReleaseView.as_view(),
        name='api-tower-release-lock',
    ),
    path(
        'api/staff/submissions/',
        StaffSubmissionList.as_view(),
        name='api-staff-submissions',
    ),
    path(
        'api/staff/submissions/<int:pk>/review/',
        StaffSubmissionReview.as_view(),
        name='api-staff-submission-review',
    ),
    # mode-trail-discovery: player trail state + staff per-session routes.
    path('api/trail/state/', TrailStateView.as_view(), name='api-trail-state'),
    path('api/trail/next/', TrailNextView.as_view(), name='api-trail-next'),
    path(
        'api/trail/leaderboard/',
        TrailLeaderboardView.as_view(),
        name='api-trail-leaderboard',
    ),
    path(
        'api/staff/sessions/<int:pk>/trail-routes/',
        SessionTrailRoutesView.as_view(),
        name='api-staff-session-trail-routes',
    ),
    path(
        'api/staff/sessions/<int:pk>/trail-routes/auto-generate/',
        SessionTrailRoutesGenerateView.as_view(),
        name='api-staff-session-trail-routes-generate',
    ),
    path(
        'api/staff/sessions/<int:pk>/trail-reveal-start/',
        SessionTrailRevealStartView.as_view(),
        name='api-staff-session-trail-reveal-start',
    ),
    path(
        'api/staff/sessions/<int:pk>/trail-leaderboard/',
        SessionTrailLeaderboardView.as_view(),
        name='api-staff-session-trail-leaderboard',
    ),
    # score-multipliers: nested under games/sessions. The DRF admin
    # router registered below never matches these extra suffixes, so
    # resolution falls through cleanly (same trick as organize/urls.py).
    path(
        'api/staff/games/<int:game_id>/score-multipliers/',
        GameScoreMultiplierListCreate.as_view(),
        name='api-staff-game-multipliers',
    ),
    path(
        'api/staff/games/<int:game_id>/score-multipliers/<int:pk>/',
        GameScoreMultiplierDetail.as_view(),
        name='api-staff-game-multiplier-detail',
    ),
    path(
        'api/staff/sessions/<int:session_id>/score-multipliers/',
        SessionScoreMultiplierListCreate.as_view(),
        name='api-staff-session-multipliers',
    ),
    path(
        'api/staff/sessions/<int:session_id>/score-multipliers/<int:pk>/activate/',
        SessionScoreMultiplierToggle.as_view(target_state=True),
        name='api-staff-session-multiplier-activate',
    ),
    path(
        'api/staff/sessions/<int:session_id>/score-multipliers/<int:pk>/deactivate/',
        SessionScoreMultiplierToggle.as_view(target_state=False),
        name='api-staff-session-multiplier-deactivate',
    ),
    path(
        'api/sessions/<int:pk>/score-multipliers/active/',
        SessionActiveMultipliersView.as_view(),
        name='api-session-active-multipliers',
    ),
    # BLE proximity substrate + dementors mode (mode-dementors-ble).
    path(
        'api/proximity/identity/',
        ProximityIdentityView.as_view(),
        name='api-proximity-identity',
    ),
    path(
        'api/proximity/reports/',
        ProximityReportView.as_view(),
        name='api-proximity-reports',
    ),
    path(
        'api/proximity/capability/',
        ProximityCapabilityView.as_view(),
        name='api-proximity-capability',
    ),
    path('api/dementors/me/', DementorMeView.as_view(), name='api-dementors-me'),
    path(
        'api/staff/dementors/session/<int:pk>/totals/',
        StaffDementorTotalsView.as_view(),
        name='api-staff-dementor-totals',
    ),
    # Wearable badge hardware (wearable-badge-hardware).
    path(
        'api/gateway/ingest/',
        GatewayIngestView.as_view(),
        name='api-gateway-ingest',
    ),
    path(
        'api/staff/badges/',
        StaffBadgeListView.as_view(),
        name='api-staff-badges',
    ),
    path(
        'api/staff/badges/<int:pk>/assign/',
        StaffBadgeAssignView.as_view(),
        name='api-staff-badge-assign',
    ),
    path(
        'api/staff/badges/<int:pk>/collect/',
        StaffBadgeCollectView.as_view(),
        name='api-staff-badge-collect',
    ),
    path(
        'api/staff/gateways/',
        StaffGatewayListView.as_view(),
        name='api-staff-gateways',
    ),
    path('api/staff/', include(admin_router.urls)),
    path(
        'api/staff/game-state/reset-scores/',
        ResetScoresView.as_view(),
        name='api-staff-reset-scores',
    ),
    path('api/', include('organize.urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('chaining/', include('smart_selects.urls')),

] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) \
              + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

