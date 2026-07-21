"""Websocket URL routes (realtime-and-notifications)."""

from django.urls import re_path

from game.consumers import SessionRealtimeConsumer

websocket_urlpatterns = [
    re_path(
        r'^ws/session/(?P<session_id>\d+)/$',
        SessionRealtimeConsumer.as_asgi(),
    ),
]
