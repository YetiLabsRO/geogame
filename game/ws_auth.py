"""Token authentication for the websocket scope.

The socket authenticates with the same DRF token the REST API uses.
Chosen transport: a `token` QUERY PARAMETER on the websocket URL
(`/ws/session/<id>/?token=<key>`). The browser WebSocket API cannot set
an `Authorization` header, and smuggling the token through the
`Sec-WebSocket-Protocol` subprotocol header both abuses the field's
semantics and breaks intermediaries that echo the negotiated
subprotocol. The query-parameter trade-off (the token may appear in
server access logs) is acceptable here: tokens are already long-lived
DRF tokens, traffic is TLS in production, and the socket is read-only
broadcast. Documented in the realtime-updates change notes.

A second, disjoint form exists for the big-screen overview
(`?overview=<link-token>`, live-overview capability). It resolves a
`SessionOverviewLink` rather than a user, and a scope presenting BOTH
forms is refused rather than merged — a share token must never be able
to widen a real user's admission, nor inherit one.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _user_for_token(key):
    from rest_framework.authtoken.models import Token
    try:
        token = Token.objects.select_related('user').get(key=key)
    except Token.DoesNotExist:
        return AnonymousUser()
    if not token.user.is_active:
        return AnonymousUser()
    return token.user


@database_sync_to_async
def _overview_link_for_token(key):
    """A usable share link, or None. Revoked and expired look the same."""
    from game.models import SessionOverviewLink
    return (
        SessionOverviewLink.objects.usable()
        .filter(token=key)
        .select_related('session')
        .first()
    )


class TokenAuthMiddleware:
    """Resolve `?token=<drf-key>` to `scope['user']`, or `?overview=
    <link-token>` to `scope['overview_link']` — never both."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        key = (query.get('token') or [None])[0]
        overview_key = (query.get('overview') or [None])[0]
        scope = dict(scope)
        scope['user'] = AnonymousUser()
        scope['overview_link'] = None
        scope['auth_conflict'] = bool(key and overview_key)
        if scope['auth_conflict']:
            return await self.inner(scope, receive, send)
        if key:
            scope['user'] = await _user_for_token(key)
        elif overview_key:
            scope['overview_link'] = await _overview_link_for_token(overview_key)
        return await self.inner(scope, receive, send)
