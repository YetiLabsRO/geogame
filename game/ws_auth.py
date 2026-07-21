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


class TokenAuthMiddleware:
    """Resolve `?token=<drf-key>` on the websocket URL to `scope['user']`."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        key = (query.get('token') or [None])[0]
        scope = dict(scope)
        scope['user'] = await _user_for_token(key) if key else AnonymousUser()
        return await self.inner(scope, receive, send)
