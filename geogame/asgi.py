"""
ASGI config for geogame project (realtime-and-notifications).

Exposes a Channels `ProtocolTypeRouter`: HTTP requests are served by the
regular Django application (identical behavior to WSGI), websocket
connections go through the token-auth middleware into the session-scoped
realtime consumer. `geogame/wsgi.py` keeps working for deployments that
do not enable real-time.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geogame.settings')

# Initialise Django BEFORE importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from game.routing import websocket_urlpatterns  # noqa: E402
from game.ws_auth import TokenAuthMiddleware  # noqa: E402

# mcp-authoring-server: streamable-HTTP MCP endpoint mounted at
# /mcp/authoring/. Built lazily on first hit and fully import-guarded so
# a missing SDK or build error can never take down HTTP serving.
_MCP_PREFIX = '/mcp/authoring'
_mcp_app = None


def _get_mcp_app():
    global _mcp_app
    if _mcp_app is None:
        from authoring.mcp_server import authoring_asgi_app
        _mcp_app = authoring_asgi_app()
    return _mcp_app


async def _http_router(scope, receive, send):
    path = scope.get('path', '')
    if path == _MCP_PREFIX or path.startswith(_MCP_PREFIX + '/'):
        try:
            app = _get_mcp_app()
        except Exception:  # noqa: BLE001 - never break HTTP serving
            app = None
        if app is not None:
            await app(scope, receive, send)
            return
    await django_asgi_app(scope, receive, send)


application = ProtocolTypeRouter({
    'http': _http_router,
    'websocket': TokenAuthMiddleware(URLRouter(websocket_urlpatterns)),
})
