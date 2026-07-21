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

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': TokenAuthMiddleware(URLRouter(websocket_urlpatterns)),
})
