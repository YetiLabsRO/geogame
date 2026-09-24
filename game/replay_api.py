"""Staff replay endpoint (session-replay capability).

One request returns everything needed to scrub a recorded Session, so
dragging the timeline never touches the backend — the property the
simulator's replay already has, extended to real games.
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.location_api import parse_window_bound
from game.replay import build_replay_bundle
from organize.models import Session


class StaffSessionReplayView(APIView):
    """GET: the replay bundle for a Session.

    Query params: `interval_seconds` (frame width, subject to a floor
    and to coarsening when the frame cap would be exceeded), and a
    `from`/`to` ISO-datetime window.
    """

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        window_from, error = parse_window_bound(
            request.query_params.get('from'), 'from',
        )
        if error is None:
            window_to, error = parse_window_bound(request.query_params.get('to'), 'to')
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_replay_bundle(
            session,
            interval_seconds=request.query_params.get('interval_seconds'),
            window_from=window_from,
            window_to=window_to,
        ))
