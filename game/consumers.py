"""Session-scoped realtime consumer (realtime-and-notifications).

One websocket endpoint per Session. A caller is admitted only when it
presents a valid DRF token (see `game.ws_auth`) AND either is staff or
holds an active TeamMembership on that Session. Admitted sockets join
exactly one channel-layer group — `session_<id>` — so events never leak
across Sessions. The socket is server→client broadcast; the only client
message honoured is a lightweight `{"type": "ping"}` heartbeat.

A second admission path exists for the big-screen overview
(live-overview): a `SessionOverviewLink` token admits an anonymous,
read-only viewer bound to exactly one Session. Such a connection is
marked RESTRICTED and receives only the event types the overview
renders — see `OVERVIEW_EVENTS`. The filter is an allowlist checked on
the way out, so a future event type is invisible to share viewers until
someone adds it deliberately.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from game.events import overview_link_group, session_group

# Application close codes (4xxx range is reserved for applications).
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_REALTIME_DISABLED = 4423

# Event types a share-link viewer may receive. Everything the overview
# actually paints, and nothing else — `dementor.tick` is excluded by
# construction rather than by omission: it carries a per-player role and
# energy snapshot the overview never renders and an anonymous viewer has
# no business receiving.
OVERVIEW_EVENTS = frozenset({
    'tower.ownership_changed',
    'zone.control_changed',
    'scoreboard.updated',
    'bonus.appeared',
    'session.state_changed',
})


@database_sync_to_async
def _admission(session_id, user, overview_link=None, conflict=False):
    """Return an application close code, or None when admission is granted."""
    from organize.models import Session

    # Presenting both credentials is refused outright rather than
    # resolved to whichever is stronger: the union of a user token and a
    # share token is not a thing either of them was issued for.
    if conflict:
        return CLOSE_UNAUTHORIZED
    authenticated = user is not None and getattr(user, 'is_authenticated', False)
    if not authenticated and overview_link is None:
        return CLOSE_UNAUTHORIZED
    session = Session.objects.select_related('game').filter(pk=session_id).first()
    if session is None:
        return CLOSE_NOT_FOUND
    if not session.effective('realtime_enabled'):
        return CLOSE_REALTIME_DISABLED
    if overview_link is not None:
        # A link is bound to one Session; it opens no other socket.
        # `usable()` already filtered revoked and expired links, so
        # reaching here means the link is live right now.
        return None if overview_link.session_id == session.id else CLOSE_FORBIDDEN
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
    #: Set only for a share-link viewer, so revocation can reach it.
    link_group_name = None
    #: True for a share-link viewer: anonymous, read-only, allowlisted.
    restricted = False

    async def connect(self):
        session_id = int(self.scope['url_route']['kwargs']['session_id'])
        overview_link = self.scope.get('overview_link')
        close_code = await _admission(
            session_id,
            self.scope.get('user'),
            overview_link=overview_link,
            conflict=bool(self.scope.get('auth_conflict')),
        )
        if close_code is not None:
            await self.close(code=close_code)
            return
        self.restricted = overview_link is not None
        self.group_name = session_group(session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        if self.restricted:
            self.link_group_name = overview_link_group(overview_link.token)
            await self.channel_layer.group_add(
                self.link_group_name, self.channel_name,
            )
        await self.accept()

    async def disconnect(self, code):
        if self.group_name is not None:
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name,
            )
        if self.link_group_name is not None:
            await self.channel_layer.group_discard(
                self.link_group_name, self.channel_name,
            )

    async def receive_json(self, content, **kwargs):
        # Broadcast-only socket: honour the heartbeat, ignore the rest.
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def session_event(self, message):
        """Fan a `broadcast_session_event` envelope out to this client."""
        envelope = message['envelope']
        if self.restricted and envelope.get('type') not in OVERVIEW_EVENTS:
            return
        await self.send_json(envelope)

    async def overview_revoked(self, message):
        """The share link that admitted this socket was revoked."""
        await self.close(code=CLOSE_FORBIDDEN)
