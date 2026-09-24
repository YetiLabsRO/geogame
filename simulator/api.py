"""Staff control endpoints for the game simulator (game-simulator-backend).

Every endpoint is staff-only (`IsAdminUser`). Nothing here runs
automatically: create() runs `setup()` once, and each control endpoint
advances the run exactly as far as asked. `DELETE` tears down every
sim-created row (see `simulator.driver.SimulationDriver.teardown`).
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from organize.models import IllegalTransition
from simulator.driver import SimulationDriver
from simulator.models import SimulationEvent, SimulationRun
from simulator.serializers import SimulationEventSerializer, SimulationRunSerializer

# Top-level request keys folded into SimulationRun.config by create();
# see simulator/driver.py for their meaning and defaults.
CONFIG_KEYS = (
    'template_game_id', 'game_name', 'n_players', 'n_teams', 'mode',
    'dementors_enabled', 'tick_seconds', 'capture_probability',
    'step_meters', 'radius_m', 'center_lat', 'center_lng',
    'duration_minutes', 'ble_very_close_m', 'ble_near_m', 'proximity_meters',
)


class SimulationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Simulation run is not in a state that allows this action.'
    default_code = 'simulation_conflict'


def _get_run(pk):
    return get_object_or_404(SimulationRun, pk=pk)


class SimulationRunListCreateView(APIView):
    """GET: list runs. POST: create a run and immediately `setup()` it."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        runs = SimulationRun.objects.all()
        return Response(SimulationRunSerializer(runs, many=True).data)

    def post(self, request):
        data = request.data
        config = dict(data.get('config') or {})
        for key in CONFIG_KEYS:
            if key in data:
                config[key] = data[key]
        try:
            seed = int(data.get('seed', 0) or 0)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'seed must be an integer.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        run = SimulationRun.objects.create(
            name=data.get('name') or 'Simulation run',
            created_by=request.user,
            seed=seed,
            config=config,
        )
        try:
            SimulationDriver(run).setup()
        except Exception as exc:  # setup failure: leave nothing behind
            run.delete()
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        run.refresh_from_db()
        return Response(SimulationRunSerializer(run).data, status=status.HTTP_201_CREATED)


class SimulationRunDetailView(APIView):
    """GET: run detail + a live `state()` snapshot. DELETE: full teardown."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        run = _get_run(pk)
        payload = SimulationRunSerializer(run).data
        payload['state'] = SimulationDriver(run).state() if run.session_id else None
        return Response(payload)

    def delete(self, request, pk):
        run = _get_run(pk)
        SimulationDriver(run).teardown()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SimulationRunStepView(APIView):
    """POST {ticks?}: advance the run by `ticks` (default 1) synchronously."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        run = _get_run(pk)
        ticks = max(1, int(request.data.get('ticks', 1) or 1))
        driver = SimulationDriver(run)
        try:
            for _ in range(ticks):
                snapshot = driver.step()
        except ValueError as exc:
            raise SimulationConflict(str(exc)) from exc
        return Response(snapshot)


class SimulationRunPlayView(APIView):
    """POST {ticks}: like step, but named for a "play N ticks" client action."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        run = _get_run(pk)
        ticks = max(1, int(request.data.get('ticks', 1) or 1))
        driver = SimulationDriver(run)
        try:
            results = driver.play(ticks)
        except ValueError as exc:
            raise SimulationConflict(str(exc)) from exc
        return Response(results[-1] if results else driver.state())


class SimulationRunPauseView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        run = _get_run(pk)
        try:
            SimulationDriver(run).pause()
        except IllegalTransition as exc:
            raise SimulationConflict(str(exc)) from exc
        run.refresh_from_db()
        return Response(SimulationRunSerializer(run).data)


class SimulationRunStopView(APIView):
    """POST: finish the run's Session (closes ownerships; history is kept)."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        run = _get_run(pk)
        try:
            SimulationDriver(run).stop()
        except IllegalTransition as exc:
            raise SimulationConflict(str(exc)) from exc
        run.refresh_from_db()
        return Response(SimulationRunSerializer(run).data)


class SimulationRunTimelineView(APIView):
    """GET: the run's full append-only SimulationEvent tape, tick-ordered."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        run = _get_run(pk)
        events = SimulationEvent.objects.filter(run=run).order_by('tick', 'id')
        return Response(SimulationEventSerializer(events, many=True).data)
