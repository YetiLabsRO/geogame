"""Staff control endpoints for the game simulator (game-simulator-backend)."""
from django.urls import path

from simulator import api

urlpatterns = [
    path(
        'api/staff/simulator/runs/',
        api.SimulationRunListCreateView.as_view(),
        name='simulator-run-list',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/',
        api.SimulationRunDetailView.as_view(),
        name='simulator-run-detail',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/step/',
        api.SimulationRunStepView.as_view(),
        name='simulator-run-step',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/play/',
        api.SimulationRunPlayView.as_view(),
        name='simulator-run-play',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/pause/',
        api.SimulationRunPauseView.as_view(),
        name='simulator-run-pause',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/stop/',
        api.SimulationRunStopView.as_view(),
        name='simulator-run-stop',
    ),
    path(
        'api/staff/simulator/runs/<int:pk>/timeline/',
        api.SimulationRunTimelineView.as_view(),
        name='simulator-run-timeline',
    ),
]
