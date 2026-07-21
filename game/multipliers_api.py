"""REST API for score multipliers (score-multipliers capability).

Three URL families, wired in geogame/urls.py:

- ``/api/staff/games/{game_id}/score-multipliers/`` (+ ``{pk}/``) —
  template authoring on a Game (typically SCHEDULED arcs). Mutations
  require template edit rights (`Game.can_edit`), matching the
  challenge-bank rule: runners clone a game to personalise it.
- ``/api/staff/sessions/{session_id}/score-multipliers/`` (+
  ``{pk}/activate|deactivate/``) — live runner control on one Session:
  drop a RANDOM_BONUS / MANUAL multiplier, toggle it on or off. The
  list shows the union of Session-owned and Game-owned rows so the
  console sees the whole picture.
- ``/api/sessions/{pk}/score-multipliers/active/`` — read-only list of
  the multipliers in effect right now, for the player map/scoreboard
  ("Double points now", "Bonus at Old Tower"). Staff or a member of the
  session may read it.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import ScoreMultiplier, active_multipliers_for_session
from organize.models import Game, Session


def active_multiplier_payload(session, at=None):
    """Wire shape for the multipliers in effect for `session` right now."""
    payload = []
    for multiplier in active_multipliers_for_session(session, at=at):
        _start, end = multiplier.resolved_window(session=session)
        payload.append({
            'id': multiplier.id,
            'factor': multiplier.factor,
            'scope': multiplier.scope,
            'multiplier_type': multiplier.multiplier_type,
            'tower_id': multiplier.tower_id,
            'tower_name': multiplier.tower.name if multiplier.tower_id else None,
            'zone_id': multiplier.zone_id,
            'zone_name': multiplier.zone.name if multiplier.zone_id else None,
            'label': multiplier.label,
            'active_until': end.isoformat() if end else None,
            'owned_by': 'session' if multiplier.session_id else 'game',
        })
    return payload


class ScoreMultiplierSerializer(serializers.ModelSerializer):
    """Staff payload for ScoreMultiplier rows.

    Ownership (`game` / `session`) always comes from the URL, never the
    body; the serializer surfaces both read-only so clients can tell a
    template row from a live one on the session console.
    """

    tower_name = serializers.CharField(
        source='tower.name', read_only=True, default=None,
    )
    zone_name = serializers.CharField(
        source='zone.name', read_only=True, default=None,
    )
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True, default=None,
    )

    class Meta:
        model = ScoreMultiplier
        fields = (
            'id', 'game', 'session', 'scope',
            'tower', 'tower_name', 'zone', 'zone_name',
            'multiplier_type', 'factor', 'is_active',
            'window_start_offset', 'window_end_offset',
            'starts_at', 'ends_at', 'label',
            'created_by', 'created_by_username', 'created_at',
        )
        read_only_fields = ('game', 'session', 'created_by', 'created_at')

    _MODEL_FIELDS = (
        'scope', 'tower', 'zone', 'multiplier_type', 'factor', 'is_active',
        'window_start_offset', 'window_end_offset', 'starts_at', 'ends_at',
    )

    def validate(self, attrs):
        """Run model validation up-front so bad input is a 400, not a 500.

        Builds the would-be row (write payload over instance values,
        with the owner from the view's context) and calls its clean().
        """
        data = {}
        for field in self._MODEL_FIELDS:
            if field in attrs:
                data[field] = attrs[field]
            elif self.instance is not None:
                data[field] = getattr(self.instance, field)
        candidate = ScoreMultiplier(
            game=self.context.get('owner_game') or (
                self.instance.game if self.instance is not None else None
            ),
            session=self.context.get('owner_session') or (
                self.instance.session if self.instance is not None else None
            ),
            **data,
        )
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            detail = getattr(exc, 'message_dict', None) or exc.messages
            raise serializers.ValidationError(detail)
        return attrs


def _require_template_edit(game, user):
    if not game.can_edit(user):
        raise PermissionDenied(
            'Only the game creator may manage its score multipliers. '
            'Clone the game to personalise it.',
        )


class GameScoreMultiplierListCreate(generics.ListCreateAPIView):
    """List / author a Game's template multipliers (task 3.1)."""

    permission_classes = [IsAdminUser]
    serializer_class = ScoreMultiplierSerializer

    def _game(self):
        return get_object_or_404(Game, pk=self.kwargs['game_id'])

    def get_queryset(self):
        return (
            ScoreMultiplier.objects
            .filter(game_id=self.kwargs['game_id'])
            .select_related('tower', 'zone', 'created_by')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method != 'GET':
            context['owner_game'] = self._game()
        return context

    def perform_create(self, serializer):
        game = self._game()
        _require_template_edit(game, self.request.user)
        serializer.save(game=game, created_by=self.request.user)


class GameScoreMultiplierDetail(generics.RetrieveUpdateDestroyAPIView):
    """Edit / delete one template multiplier (task 3.1)."""

    permission_classes = [IsAdminUser]
    serializer_class = ScoreMultiplierSerializer

    def get_queryset(self):
        return (
            ScoreMultiplier.objects
            .filter(game_id=self.kwargs['game_id'])
            .select_related('tower', 'zone', 'created_by')
        )

    def perform_update(self, serializer):
        _require_template_edit(serializer.instance.game, self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        _require_template_edit(instance.game, self.request.user)
        instance.delete()


class SessionScoreMultiplierListCreate(generics.ListCreateAPIView):
    """Runner console: list everything affecting a Session, create live rows.

    GET returns the union of Session-owned and Game-owned multipliers
    (the effective set); POST always creates a Session-owned row
    (MANUAL toggle or RANDOM_BONUS drop — task 4.1).
    """

    permission_classes = [IsAdminUser]
    serializer_class = ScoreMultiplierSerializer

    def _session(self):
        return get_object_or_404(
            Session.objects.select_related('game'),
            pk=self.kwargs['session_id'],
        )

    def get_queryset(self):
        session = self._session()
        return (
            ScoreMultiplier.objects
            .filter(Q(session_id=session.id) | Q(game_id=session.game_id))
            .select_related('tower', 'zone', 'created_by')
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method != 'GET':
            context['owner_session'] = self._session()
        return context

    def perform_create(self, serializer):
        serializer.save(session=self._session(), created_by=self.request.user)


class SessionScoreMultiplierToggle(APIView):
    """POST .../{pk}/activate/ or .../{pk}/deactivate/ (task 4.2).

    Flips `is_active` on any multiplier reachable from the Session
    (its own rows or its Game's) — the live MANUAL switch. Only worth
    accrued from this instant forward is affected; finalized locked
    score is never rewritten.
    """

    permission_classes = [IsAdminUser]
    target_state = True

    def post(self, request, session_id, pk):
        session = get_object_or_404(
            Session.objects.select_related('game'), pk=session_id,
        )
        multiplier = get_object_or_404(
            ScoreMultiplier.objects.filter(
                Q(session_id=session.id) | Q(game_id=session.game_id),
            ),
            pk=pk,
        )
        multiplier.is_active = self.target_state
        multiplier.save(update_fields=['is_active'])
        return Response(
            ScoreMultiplierSerializer(multiplier).data,
            status=status.HTTP_200_OK,
        )


class SessionActiveMultipliersView(APIView):
    """Read-only in-effect list for map/scoreboard banners (task 4.3).

    Staff can read any session's; players need a membership on the
    session (same visibility rule as the scoreboard).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        session = Session.objects.filter(pk=pk).select_related('game').first()
        if session is None:
            return Response(
                {'detail': 'Session not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not request.user.is_staff and not (
            request.user.profile.memberships
            .filter(team__session=session)
            .exists()
        ):
            return Response(
                {'detail': 'Not your session.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(active_multiplier_payload(session))
