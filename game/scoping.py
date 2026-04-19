"""Scoping mixins for viewsets.

Two flavors:

- `GameScopedViewSetMixin` filters the queryset by the authenticated
  user's current Session's Game. Use on endpoints serving event config:
  Zone, Tower, Challenge, TeamGroup.
- `SessionScopedViewSetMixin` filters by the current Session directly.
  Use on endpoints serving runtime state: Team, ownerships, submissions,
  Invites.

Both resolve the scope from `request.user.profile.current_session`. If
that is None (user has not selected a session) the mixin returns an
empty queryset — the CurrentSessionView endpoint is responsible for
surfacing a picker in that case.

Each mixin has a single required class attribute:
- `game_scope_field` (for GameScopedViewSetMixin) — the lookup path from
  the model to the Game FK, e.g. 'game' for Zone or 'team__session__game'
  for TeamTowerChallenge.
- `session_scope_field` (for SessionScopedViewSetMixin) — analogous, but
  targeting Session.

The mixin uses a sentinel (`_SCOPE_UNSET`) so subclasses that forget to
declare the field blow up loudly instead of silently returning every row.
"""
from django.core.exceptions import ImproperlyConfigured

_SCOPE_UNSET = object()


def _current_session(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    return profile.current_session


class GameScopedViewSetMixin:
    """Scope the queryset to the caller's current Session's Game."""

    game_scope_field = _SCOPE_UNSET

    def get_queryset(self):
        qs = super().get_queryset()
        if self.game_scope_field is _SCOPE_UNSET:
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} must set game_scope_field.',
            )
        session = _current_session(self.request)
        if session is None:
            return qs.none()
        return qs.filter(**{self.game_scope_field: session.game_id})


class SessionScopedViewSetMixin:
    """Scope the queryset to the caller's current Session."""

    session_scope_field = _SCOPE_UNSET

    def get_queryset(self):
        qs = super().get_queryset()
        if self.session_scope_field is _SCOPE_UNSET:
            raise ImproperlyConfigured(
                f'{self.__class__.__name__} must set session_scope_field.',
            )
        session = _current_session(self.request)
        if session is None:
            return qs.none()
        return qs.filter(**{self.session_scope_field: session.id})
