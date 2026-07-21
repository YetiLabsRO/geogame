"""DRF endpoints for the BLE proximity substrate + dementors mode.

Player-facing:
- POST /api/proximity/identity/    issue/rotate the ephemeral BLE token
- POST /api/proximity/reports/     submit one batch of seen tokens+RSSI
- POST /api/proximity/capability/  BLE self-check result (gate)
- GET  /api/dementors/me/          own role/energy/live delta (polling)

Staff-facing:
- GET /api/staff/dementors/session/<pk>/totals/   role totals + feed

The server is authoritative throughout: phones only ever submit raw
observations; energy/roles are read-only outputs of the server tick.
Real-time Channels push is not wired yet — polling GET /api/dementors/me/
is the documented fallback (see tasks.md implementation notes).
"""
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.dementors import run_tick
from game.models import DementorState, ProximityIdentity, ProximityReport
from game.proximity import (
    clean_observations,
    report_rate_exceeded,
    resolvable_identities,
)
from organize.models import Session, TeamMembership


def _current_session_or_response(request):
    """(session, None) for a usable current session, else (None, Response)."""
    session = request.user.profile.current_session
    if session is None:
        return None, Response(
            {'detail': 'You are not in any session.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return session, None


def _ble_refusal(session, profile):
    """403 Response when the Game requires BLE and this device failed
    its self-check; None otherwise (unknown capability is admitted)."""
    if not session.effective('require_ble_capable'):
        return None
    if profile.attributes.get('ble_capable') is False:
        return Response(
            {
                'detail': (
                    'This game requires a BLE-capable phone. Your device '
                    'failed the Bluetooth self-check, so it cannot join '
                    'proximity gameplay.'
                ),
                'require_ble_capable': True,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class ProximityCapabilityView(APIView):
    """Record the device's BLE self-check and report admission.

    POST {"ble_capable": true|false}. When the effective
    `require_ble_capable` is on, a device that reports False is refused
    proximity gameplay with a clear message; without the flag the device
    is admitted but MAY be excluded from proximity play.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        session, error = _current_session_or_response(request)
        if error is not None:
            return error
        ble_capable = request.data.get('ble_capable')
        if not isinstance(ble_capable, bool):
            return Response(
                {'detail': 'ble_capable must be a boolean.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = request.user.profile
        profile.attributes['ble_capable'] = ble_capable
        profile.save(update_fields=['attributes'])

        required = bool(session.effective('require_ble_capable'))
        admitted = ble_capable or not required
        detail = 'Device admitted to proximity gameplay.'
        if not admitted:
            detail = (
                'This game requires a BLE-capable phone; this device '
                'failed the Bluetooth self-check.'
            )
        elif not ble_capable:
            detail = (
                'Device admitted, but without BLE it is excluded from '
                'proximity gameplay.'
            )
        return Response({
            'ble_capable': ble_capable,
            'require_ble_capable': required,
            'admitted': admitted,
            'detail': detail,
        })


class ProximityIdentityView(APIView):
    """Issue (or rotate) the caller's ephemeral advertising identity.

    Returns the current active token while it is fresh; issues a new one
    when the rotation interval elapsed or the body sets {"rotate": true}.
    The token→player mapping never leaves the server.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        session, error = _current_session_or_response(request)
        if error is not None:
            return error
        profile = request.user.profile
        refusal = _ble_refusal(session, profile)
        if refusal is not None:
            return refusal

        now = timezone.now()
        force_rotate = bool(request.data.get('rotate', False))
        identity = ProximityIdentity.current_for(session, profile)
        rotated = False
        if (
            identity is None
            or force_rotate
            or (identity.rotates_at is not None and identity.rotates_at <= now)
        ):
            identity = ProximityIdentity.issue(session, profile, now=now)
            rotated = True

        return Response({
            'token': identity.token,
            'rotates_at': identity.rotates_at,
            'rotated': rotated,
            'report_interval_seconds': session.effective('ble_report_interval_seconds'),
            'scan_duty_cycle_percent': session.effective('ble_scan_duty_cycle_percent'),
            'freshness_window_seconds': session.effective('ble_freshness_window_seconds'),
        })


class ProximityReportView(APIView):
    """Ingest one phone's batch of observed tokens + RSSI.

    Untrusted input: entries are shape-validated and size-capped, tokens
    that do not resolve to a live (or freshly-rotated) identity in this
    session are discarded while the rest of the batch is recorded, and
    implausible report rates are refused with 429. Ingestion triggers the
    server tick (derivation + economy) — there is no cron dependency.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        session, error = _current_session_or_response(request)
        if error is not None:
            return error
        profile = request.user.profile
        refusal = _ble_refusal(session, profile)
        if refusal is not None:
            return refusal

        identity = ProximityIdentity.current_for(session, profile)
        if identity is None:
            return Response(
                {'detail': 'Request an advertising identity before reporting.'},
                status=status.HTTP_409_CONFLICT,
            )

        now = timezone.now()
        if report_rate_exceeded(session, profile, now=now):
            return Response(
                {'detail': 'Reporting too fast; slow down to the configured cadence.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        kept, discarded = clean_observations(request.data.get('observations'))
        token_map = resolvable_identities(session, now=now)
        recorded = []
        for entry in kept:
            seen = token_map.get(entry['token'])
            if seen is None or seen.player_id == profile.pk:
                discarded += 1
                continue
            recorded.append(entry)

        report = ProximityReport.objects.create(
            session=session,
            reporter=identity,
            player=profile,
            observations=recorded,
            reported_at=request.data.get('reported_at') or None,
        )
        # Tick with a timestamp taken after persisting so this very
        # report is inside the freshness window it triggers.
        events = run_tick(session)
        return Response(
            {
                'id': report.id,
                'recorded': len(recorded),
                'discarded': discarded,
                'events_derived': len(events),
            },
            status=status.HTTP_201_CREATED,
        )


class DementorMeView(APIView):
    """Own role, energy and live drain/gain delta (polling fallback).

    Values come exclusively from server state — the device's own
    proximity claims never show up here except through the server tick.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session, error = _current_session_or_response(request)
        if error is not None:
            return error
        if not session.effective('dementors_enabled'):
            return Response(
                {'detail': 'Dementors mode is not enabled for this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        profile = request.user.profile
        state = DementorState.objects.filter(session=session, player=profile).first()
        if state is None:
            return Response(
                {'detail': 'You are not part of this dementors run.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        window = session.effective('ble_freshness_window_seconds')
        has_fresh_report = ProximityReport.objects.filter(
            session=session,
            player=profile,
            received_at__gte=now - timedelta(seconds=window),
        ).exists()

        if state.last_delta < 0:
            trend = 'DRAINING'
        elif state.last_delta > 0:
            trend = 'GAINING'
        else:
            trend = 'STABLE'

        return Response({
            'role': state.role,
            'energy': round(state.energy, 2),
            'starting_energy': session.effective('dementor_starting_energy'),
            'conversion_threshold': session.effective('dementor_conversion_threshold'),
            'alive': state.alive,
            'last_delta': round(state.last_delta, 3),
            'trend': trend,
            'last_tick_at': state.last_tick_at,
            'reports_stale': not has_fresh_report,
            'report_interval_seconds': session.effective('ble_report_interval_seconds'),
            'freshness_window_seconds': window,
        })


class StaffDementorTotalsView(APIView):
    """Live role totals + per-player feed for the staff dashboard.

    Polling endpoint (the graceful fallback for the future Channels
    push); also feeds an optional map/tablet view.
    """

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        enabled = bool(session.effective('dementors_enabled'))
        states = (
            DementorState.objects
            .filter(session=session)
            .select_related('player__user')
            .order_by('player__user__username')
        )
        team_by_player = {}
        memberships = (
            TeamMembership.objects
            .filter(team__session=session, is_active=True)
            .select_related('team')
        )
        for membership in memberships:
            team_by_player[membership.user_id] = membership.team.name

        wizards = sum(
            1 for s in states if s.alive and s.role == DementorState.WIZARD
        )
        dementors = sum(
            1 for s in states if s.alive and s.role == DementorState.DEMENTOR
        )
        out_of_play = sum(1 for s in states if not s.alive)
        return Response({
            'session': session.id,
            'enabled': enabled,
            'totals': {
                'wizards': wizards,
                'dementors': dementors,
                'out_of_play': out_of_play,
            },
            'players': [
                {
                    'player_id': s.player_id,
                    'username': s.player.user.get_username(),
                    'team': team_by_player.get(s.player_id),
                    'role': s.role,
                    'energy': round(s.energy, 2),
                    'alive': s.alive,
                    'last_delta': round(s.last_delta, 3),
                    'last_tick_at': s.last_tick_at,
                }
                for s in states
            ],
        })
