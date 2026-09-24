"""Live overview endpoints (live-overview capability).

Three surfaces over one snapshot:

- `GET /api/staff/sessions/{id}/overview/` — staff, any Session.
- `GET /api/overview/{token}/` — unauthenticated, one Session, addressed
  by a revocable share link, and strictly narrower (no usernames).
- share-link management, staff-only.

The token endpoint is the first unauthenticated read of live game state
in this codebase, so it is deliberately boring: one object, read-only,
no query parameters that widen it, and a 404 for every kind of bad token
so a prober cannot tell a revoked link from one that never existed.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from game.events import broadcast_overview_revoked
from game.models import SessionOverviewLink
from game.overview import build_overview_snapshot
from organize.models import Session


class OverviewLinkThrottle(SimpleRateThrottle):
    """Rate limit keyed on the share link, not the caller.

    A wall display and a phone behind the same NAT are one address and
    two links; an address-keyed throttle would let either starve the
    other. The token is already the unit of access, so it is the unit of
    the limit too.
    """

    scope = 'overview_link'

    def get_cache_key(self, request, view):
        token = view.kwargs.get('token')
        return f'throttle_overview_link_{token}' if token else None


def _link_or_404(token):
    """Resolve a usable share link, or None.

    Every rejection — unknown, revoked, expired — returns the same
    nothing, so the response cannot be used to enumerate tokens or to
    learn that one used to be valid.
    """
    return SessionOverviewLink.objects.usable().filter(token=token).select_related(
        'session', 'session__game',
    ).first()


def _serialize_link(link, request=None):
    path = f'/staff/live/{link.token}'
    return {
        'id': link.id,
        'token': link.token,
        'label': link.label,
        'is_active': link.is_active,
        'is_usable': link.is_usable(),
        'expires_at': link.expires_at,
        'created_at': link.created_at,
        'revoked_at': link.revoked_at,
        'created_by': link.created_by.username if link.created_by else None,
        'path': path,
        'url': request.build_absolute_uri(path) if request is not None else path,
    }


class StaffSessionOverviewView(APIView):
    """The live overview snapshot for any Session."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(
            Session.objects.select_related('game'), pk=pk,
        )
        return Response(build_overview_snapshot(session, with_names=True))


class PublicOverviewView(APIView):
    """The same snapshot, addressed by a share link and without names."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [OverviewLinkThrottle]

    def get(self, request, token):
        link = _link_or_404(token)
        if link is None:
            return Response(
                {'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND,
            )
        return Response(build_overview_snapshot(link.session, with_names=False))


class StaffOverviewLinkListCreateView(APIView):
    """A Session's share links: list them, issue one."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        # Revoked links stay listed: "did I already kill the one on the
        # projector?" is the question this page exists to answer.
        links = session.overview_links.select_related('created_by')
        return Response([_serialize_link(link, request) for link in links])

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        expires_at = request.data.get('expires_at') or None
        if expires_at is not None:
            from django.utils.dateparse import parse_datetime
            parsed = parse_datetime(expires_at)
            if parsed is None:
                return Response(
                    {'detail': "Could not parse 'expires_at' as an ISO datetime."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            expires_at = parsed
        link = SessionOverviewLink.objects.create(
            session=session,
            label=(request.data.get('label') or '').strip()[:255],
            expires_at=expires_at,
            created_by=request.user,
        )
        return Response(
            _serialize_link(link, request), status=status.HTTP_201_CREATED,
        )


class StaffOverviewLinkRevokeView(APIView):
    """Revoke a share link. A state change, never a delete — the row is
    the record that the screen in the tent was switched off."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        link = get_object_or_404(
            SessionOverviewLink.objects.select_related('created_by'), pk=pk,
        )
        if link.is_active:
            link.revoke(at=timezone.now())
            # Stop the screen already on the wall, not just the next
            # request for it.
            broadcast_overview_revoked(link.token)
        return Response(_serialize_link(link, request))
