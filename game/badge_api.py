"""DRF endpoints for wearable badges + gateways (wearable-badge).

Gateway-facing:
- POST /api/gateway/ingest/   authenticated by a per-gateway token
  (X-Gateway-Token header), accepts relayed proximity + telemetry
  batches, answers with per-badge display state for the downlink.

Staff-facing (provisioning / fleet):
- GET/POST /api/staff/badges/              inventory + register
- POST     /api/staff/badges/<pk>/assign/  hand-out (bind to player/team)
- POST     /api/staff/badges/<pk>/collect/ collect (release binding)
- GET/POST /api/staff/gateways/            gateway health + register

The server stays authoritative: gateways only relay observations, and
the provisioning endpoints only manage the asset registry — game
outcomes are computed exclusively by the server tick.
"""
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.badges import (
    GATEWAY_PROTOCOL_VERSION,
    battery_low,
    device_stale,
    firmware_stale,
    process_gateway_batch,
)
from game.models import (
    BADGE_STATUS_ASSIGNED,
    BADGE_STATUS_LOST,
    BADGE_STATUS_RETIRED,
    GATEWAY_TRANSPORT_CHOICES,
    BadgeAssignment,
    BadgeDevice,
    GatewayNode,
)
from organize.models import Session, Team, UserProfile

GATEWAY_TOKEN_HEADER = 'X-Gateway-Token'


class GatewayIngestView(APIView):
    """Authenticated, versioned batch ingest for gateway relays.

    Authentication is per-gateway (the node's own token, never a player
    token); the wire-protocol version is validated before anything else
    so stale firmware fails loudly instead of half-working.
    """

    # The gateway credential is the only authentication; DRF's user
    # auth (and its CSRF coupling) is deliberately not involved.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.headers.get(GATEWAY_TOKEN_HEADER, '')
        gateway = (
            GatewayNode.objects.filter(token=token, active=True).first()
            if token else None
        )
        if gateway is None:
            return Response(
                {'detail': 'Missing or invalid gateway token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        version = request.data.get('protocol_version')
        if version != GATEWAY_PROTOCOL_VERSION:
            return Response(
                {
                    'detail': (
                        f'Unsupported protocol version {version!r}; this '
                        f'server speaks version {GATEWAY_PROTOCOL_VERSION}.'
                    ),
                    'protocol_version': GATEWAY_PROTOCOL_VERSION,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        gateway.last_seen_at = now
        gateway.save(update_fields=['last_seen_at'])
        return Response(process_gateway_batch(gateway, request.data, now=now))


def _assignment_payload(assignment):
    if assignment is None:
        return None
    return {
        'id': assignment.id,
        'session_id': assignment.session_id,
        'session': str(assignment.session),
        'player_id': assignment.player_id,
        'player': (
            assignment.player.user.get_username() if assignment.player else None
        ),
        'team_id': assignment.team_id,
        'team': assignment.team.name if assignment.team else None,
        'assigned_at': assignment.assigned_at,
    }


def _badge_row(badge, assignment, now):
    return {
        'id': badge.id,
        'badge_id': badge.badge_id,
        'hardware_mac': badge.hardware_mac,
        'firmware_version': badge.firmware_version,
        'firmware_stale': firmware_stale(badge),
        'battery_pct': badge.battery_pct,
        'battery_low': battery_low(badge),
        'status': badge.status,
        'last_seen_at': badge.last_seen_at,
        'stale': device_stale(badge.last_seen_at, now=now),
        'note': badge.note,
        'assignment': _assignment_payload(assignment),
        'unreturned': assignment.is_unreturned() if assignment else False,
    }


class StaffBadgeListView(APIView):
    """Fleet inventory (GET) + badge registration (POST)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        active = {
            assignment.badge_id: assignment
            for assignment in BadgeAssignment.objects.filter(
                released_at__isnull=True,
            ).select_related('session', 'player__user', 'team')
        }
        return Response([
            _badge_row(badge, active.get(badge.id), now)
            for badge in BadgeDevice.objects.all()
        ])

    def post(self, request):
        fields = {}
        badge_id = request.data.get('badge_id')
        if badge_id:
            fields['badge_id'] = str(badge_id)[:16]
        hardware_mac = request.data.get('hardware_mac')
        if hardware_mac:
            fields['hardware_mac'] = str(hardware_mac)[:17]
        firmware_version = request.data.get('firmware_version')
        if firmware_version:
            fields['firmware_version'] = str(firmware_version)[:32]
        note = request.data.get('note')
        if note:
            fields['note'] = str(note)
        try:
            with transaction.atomic():
                badge = BadgeDevice.objects.create(**fields)
        except IntegrityError:
            return Response(
                {'detail': 'A badge with this id or MAC is already registered.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            _badge_row(badge, None, timezone.now()),
            status=status.HTTP_201_CREATED,
        )


class StaffBadgeAssignView(APIView):
    """Hand-out: bind a badge to a player/team for a Session."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        badge = get_object_or_404(BadgeDevice, pk=pk)
        if badge.status in (BADGE_STATUS_LOST, BADGE_STATUS_RETIRED):
            return Response(
                {'detail': f'Badge is {badge.status} and cannot be handed out.'},
                status=status.HTTP_409_CONFLICT,
            )
        if badge.active_assignment() is not None:
            return Response(
                {'detail': 'Badge is already assigned; collect it first.'},
                status=status.HTTP_409_CONFLICT,
            )

        player = team = None
        player_id = request.data.get('player_id')
        team_id = request.data.get('team_id')
        if player_id is not None:
            player = UserProfile.objects.filter(pk=player_id).first()
            if player is None:
                return Response(
                    {'detail': 'Unknown player_id.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if team_id is not None:
            team = Team.objects.select_related('session').filter(pk=team_id).first()
            if team is None:
                return Response(
                    {'detail': 'Unknown team_id.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if player is None and team is None:
            return Response(
                {'detail': 'Provide player_id and/or team_id.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session = None
        session_id = request.data.get('session_id')
        if session_id is not None:
            session = Session.objects.filter(pk=session_id).first()
            if session is None:
                return Response(
                    {'detail': 'Unknown session_id.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if session is None and team is not None:
            session = team.session
        if session is None and player is not None:
            session = player.current_session
        if session is None:
            return Response(
                {
                    'detail': (
                        'Could not resolve a Session; pass session_id or a '
                        'team/player attached to one.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if team is not None and team.session_id != session.pk:
            return Response(
                {'detail': 'Team does not belong to the resolved session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = BadgeAssignment.objects.create(
            badge=badge,
            session=session,
            player=player,
            team=team,
            assigned_by=request.user,
        )
        badge.status = BADGE_STATUS_ASSIGNED
        badge.save(update_fields=['status'])
        return Response(
            _badge_row(badge, assignment, timezone.now()),
            status=status.HTTP_201_CREATED,
        )


class StaffBadgeCollectView(APIView):
    """Collect: release the active assignment (optionally marking LOST)."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        badge = get_object_or_404(BadgeDevice, pk=pk)
        assignment = badge.active_assignment()
        if assignment is None:
            return Response(
                {'detail': 'Badge has no active assignment.'},
                status=status.HTTP_409_CONFLICT,
            )
        assignment.release()
        badge.refresh_from_db(fields=['status'])
        if request.data.get('mark_lost'):
            # The badge never came back: keep the release on record but
            # flag the asset as lost for the inventory.
            badge.status = BADGE_STATUS_LOST
            badge.save(update_fields=['status'])
        return Response(_badge_row(badge, None, timezone.now()))


def _gateway_row(gateway, now):
    return {
        'id': gateway.id,
        'name': gateway.name,
        'transport': gateway.transport,
        # Staff-only surface: the credential is shown here so it can be
        # flashed into the gateway at provisioning time.
        'token': gateway.token,
        'active': gateway.active,
        'last_seen_at': gateway.last_seen_at,
        'stale': device_stale(gateway.last_seen_at, now=now),
        'coverage_note': gateway.coverage_note,
    }


class StaffGatewayListView(APIView):
    """Gateway health row (GET) + gateway registration (POST)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        return Response([
            _gateway_row(gateway, now) for gateway in GatewayNode.objects.all()
        ])

    def post(self, request):
        name = request.data.get('name')
        if not name or not isinstance(name, str):
            return Response(
                {'detail': 'name is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        transport = request.data.get('transport') or 'WIFI'
        if transport not in dict(GATEWAY_TRANSPORT_CHOICES):
            return Response(
                {'detail': 'Unknown transport.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        gateway = GatewayNode.objects.create(
            name=name[:255],
            transport=transport,
            coverage_note=str(request.data.get('coverage_note') or ''),
        )
        return Response(
            _gateway_row(gateway, timezone.now()),
            status=status.HTTP_201_CREATED,
        )
