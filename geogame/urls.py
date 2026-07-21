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
    AdminPresenceRequirementViewSet,
    AdminSessionViewSet,
    AdminTeamGroupList,
    AdminTeamMembershipViewSet,
    AdminTeamViewSet,
    AdminTowerViewSet,
    AdminZoneViewSet,
    ResetScoresView,
)
from game.api import (
    StaffSubmissionList,
    StaffSubmissionReview,
    TowerStateView,
)
from game.discovery_api import (
    DiscoveredTowersView,
    DiscoveryPingView,
    StaffRevealView,
)
from game.location_api import (
    LocationConsentView,
    LocationLiveView,
    LocationPingView,
    StaffLocationHistoryView,
)
from game.views import (
    ChallengeViewSet,
    TeamTowerChallengeViewSet,
    TeamViewSet,
    TowerViewSet,
    ZoneViewSet,
    health,
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

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health, name="health"),
    path('api/', include(router.urls)),
    path('api/towers/<int:pk>/state/', TowerStateView.as_view(), name='api-tower-state'),
    # Discovery (discovery-tracking capability).
    path(
        'api/discovery/ping/',
        DiscoveryPingView.as_view(),
        name='api-discovery-ping',
    ),
    path(
        'api/discovery/towers/',
        DiscoveredTowersView.as_view(),
        name='api-discovery-towers',
    ),
    path(
        'api/staff/discovery/reveal/',
        StaffRevealView.as_view(),
        name='api-staff-discovery-reveal',
    ),
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
        'api/staff/submissions/',
        StaffSubmissionList.as_view(),
        name='api-staff-submissions',
    ),
    path(
        'api/staff/submissions/<int:pk>/review/',
        StaffSubmissionReview.as_view(),
        name='api-staff-submission-review',
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

