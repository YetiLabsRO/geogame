"""Session-scoped realtime consumer (realtime-and-notifications).

One websocket endpoint per Session. A caller is admitted only when it
presents a valid DRF token (see `game.ws_auth`) AND either is staff or
holds an active TeamMembership on that Session. Admitted sockets join
exactly one channel-layer group — `session_<id>` — so events never leak
across Sessions. The socket is server→client broadcast; the only client
message honoured is a lightweight `{"type": "ping"}` heartbeat.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from game.events import session_group

# Application close codes (4xxx range is reserved for applications).
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_REALTIME_DISABLED = 4423


@database_sync_to_async
def _admission(session_id, user):
    """Return an application close code, or None when admission is granted."""
    from organize.models import Session

    if user is None or not getattr(user, 'is_authenticated', False):
        return CLOSE_UNAUTHORIZED
    session = Session.objects.select_related('game').filter(pk=session_id).first()
    if session is None:
        return CLOSE_NOT_FOUND
    if not session.effective('realtime_enabled'):
        return CLOSE_REALTIME_DISABLED
    if user.is_staff:
        return None
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.memberships.filter(
        is_active=True, team__session_id=session_id,
    ).exists():
        return None
    return CLOSE_FORBIDDEN


class SessionRealtimeConsumer(AsyncJsonWebsocketConsumer):
    group_name = None

    async def connect(self):
        session_id = int(self.scope['url_route']['kwargs']['session_id'])
        close_code = await _admission(session_id, self.scope.get('user'))
        if close_code is not None:
            await self.close(code=close_code)
            return
        self.group_name = session_group(session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.group_name is not None:
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name,
            )

    async def receive_json(self, content, **kwargs):
        # Broadcast-only socket: honour the heartbeat, ignore the rest.
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def session_event(self, message):
        """Fan a `broadcast_session_event` envelope out to this client."""
        await self.send_json(message['envelope'])
