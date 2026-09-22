"""Opt-in push notification delivery (realtime-and-notifications, mobile-app).

Push is advisory and best-effort: the in-app websocket / polling path
stays authoritative, and nothing in gameplay depends on a notification
arriving. A notification goes out only when EVERY gate passes:

1. the Session's effective ``push_notifications_enabled`` is True
   (Game default False, per-Session override);
2. the recipient has an active (non-revoked) ``PushSubscription`` —
   the explicit consent artifact;
3. the recipient's ``NotificationPreference`` master flag and the
   per-event toggle (steal / conquer / bonus) allow it.

Delivery is dispatched by subscription kind (``get_sender()`` returns a
``DispatchingPushSender``) so each kind uses the real transport when it is
configured and a logging stub otherwise:

- ``WEBPUSH`` subscriptions go through ``WebPushSender`` (pywebpush +
  VAPID) when ``WEBPUSH_VAPID_PUBLIC_KEY``/``WEBPUSH_VAPID_PRIVATE_KEY``
  are set;
- ``FCM`` subscriptions (native app installs) go through
  ``FcmPushSender`` (firebase-admin, HTTP v1) when
  ``FCM_CREDENTIALS_FILE`` or ``GOOGLE_APPLICATION_CREDENTIALS`` is set;
- otherwise ``LoggingPushSender`` logs what WOULD be sent and delivers
  nothing, per kind independently — e.g. Web Push can be live while FCM
  is still unconfigured.

A sender signals a dead endpoint by raising ``SubscriptionGone`` (push
service answered 404/410, or FCM reports the token unregistered / the
sender id mismatched); the subscription is then pruned (revoked) and
never sent to again.
"""

import json
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

PUSH_EVENTS = ('steal', 'conquer', 'bonus')


class PushSendError(Exception):
    """Delivery failed for a retryable / unknown reason."""


class SubscriptionGone(PushSendError):
    """The push service reports the subscription gone (HTTP 404 / 410)."""


class BasePushSender:
    """Interface: deliver `payload` (a JSON-able dict) to `subscription`."""

    def send(self, subscription, payload):  # pragma: no cover - interface
        raise NotImplementedError


class LoggingPushSender(BasePushSender):
    """Delivery stub: logs the would-be notification, sends nothing.

    Active whenever no real credentials are configured (dev, CI, tests)
    so the whole pipeline is exercisable without contacting any push
    service.
    """

    def send(self, subscription, payload):
        logger.info(
            'Push (stub, not delivered) to %s subscription %s for user %s: %s',
            subscription.kind, subscription.pk, subscription.user_id,
            json.dumps(payload),
        )


class WebPushSender(BasePushSender):
    """Real Web Push delivery via pywebpush + VAPID keys from settings.

    Dedicated to ``WEBPUSH``-kind subscriptions; routing by kind is
    ``DispatchingPushSender``'s job (see ``get_sender()`` below).
    """

    def send(self, subscription, payload):
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {
                        'p256dh': subscription.p256dh,
                        'auth': subscription.auth,
                    },
                },
                data=json.dumps(payload),
                vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
                vapid_claims={
                    'sub': f'mailto:{settings.WEBPUSH_VAPID_CLAIMS_EMAIL}',
                },
            )
        except WebPushException as exc:
            response = getattr(exc, 'response', None)
            if response is not None and response.status_code in (404, 410):
                raise SubscriptionGone(str(exc)) from exc
            raise PushSendError(str(exc)) from exc


class FcmPushSender(BasePushSender):
    """Real FCM delivery via firebase-admin (HTTP v1).

    Dedicated to ``FCM``-kind subscriptions (the native app installs).
    The Firebase Admin SDK is imported lazily (inside this method) so the
    module — and the rest of the push pipeline — imports fine without the
    SDK installed; credentials are initialised once per process.
    """

    def send(self, subscription, payload):
        import firebase_admin
        from firebase_admin import credentials, messaging

        if not firebase_admin._apps:
            if settings.FCM_CREDENTIALS_FILE:
                firebase_admin.initialize_app(
                    credentials.Certificate(settings.FCM_CREDENTIALS_FILE),
                )
            else:
                # Relies on GOOGLE_APPLICATION_CREDENTIALS (SDK default).
                firebase_admin.initialize_app()

        message = messaging.Message(
            token=subscription.fcm_token,
            notification=messaging.Notification(
                title=payload.get('title', ''),
                body=payload.get('body', ''),
            ),
            # Same keys the Web Push service worker reads (title/body/url/…).
            data={key: str(value) for key, value in payload.items()},
            android=messaging.AndroidConfig(priority='high'),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(content_available=True),
                ),
            ),
        )
        try:
            messaging.send(message)
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
            raise SubscriptionGone(str(exc)) from exc
        except Exception as exc:
            raise PushSendError(str(exc)) from exc


class DispatchingPushSender(BasePushSender):
    """Routes delivery to a per-kind sender.

    ``senders`` maps a ``PushSubscription.kind`` value to the
    ``BasePushSender`` that handles it; a kind with no entry (there is
    none today, but new kinds are inevitable) falls back to
    ``LoggingPushSender`` rather than raising.
    """

    def __init__(self, senders):
        self.senders = senders

    def send(self, subscription, payload):
        sender = self.senders.get(subscription.kind) or LoggingPushSender()
        sender.send(subscription, payload)


def get_sender():
    """The active sender: composes a per-kind ``DispatchingPushSender``.

    ``WEBPUSH`` uses real Web Push when VAPID keys exist, ``FCM`` uses
    real FCM when credentials exist, and each kind independently falls
    back to the logging stub otherwise. Resolved per call so tests can
    patch this function (or the settings) without import-order concerns.
    """
    from organize.models import PushSubscription

    if settings.WEBPUSH_VAPID_PRIVATE_KEY and settings.WEBPUSH_VAPID_PUBLIC_KEY:
        webpush_sender = WebPushSender()
    else:
        webpush_sender = LoggingPushSender()

    if settings.FCM_CREDENTIALS_FILE or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        fcm_sender = FcmPushSender()
    else:
        fcm_sender = LoggingPushSender()

    return DispatchingPushSender({
        PushSubscription.KIND_WEBPUSH: webpush_sender,
        PushSubscription.KIND_FCM: fcm_sender,
    })


def _recipient_user_ids(session):
    """Users with an ACTIVE membership on this Session's teams."""
    from organize.models import TeamMembership

    return list(
        TeamMembership.objects
        .filter(team__session=session, is_active=True)
        .values_list('user__user_id', flat=True)
        .distinct()
    )


def _build_payload(session, event, tower=None, team=None, payload=None):
    if event == 'bonus':
        body = 'A bonus is active — go grab it!'
        if payload and payload.get('name'):
            body = f"Bonus active: {payload['name']}"
        return {
            'event': 'bonus',
            'title': 'Bonus!',
            'body': body,
            'url': '/',
            'session': session.id,
        }
    verb = 'stolen' if event == 'steal' else 'conquered'
    return {
        'event': event,
        'title': f'Tower {verb}!',
        'body': f'{team.name} {verb} {tower.name}.',
        # Deep link: tapping the notification opens the tower detail.
        'url': f'/tower/{tower.id}',
        'session': session.id,
        'tower_id': tower.id,
        'team_id': team.id,
    }


def notify_session_event(session, event, *, tower=None, team=None, payload=None):
    """Send `event` ('steal' / 'conquer' / 'bonus') to consented subscribers.

    Applies every gate documented in the module docstring; prunes
    subscriptions the sender reports gone; swallows (logs) other
    delivery failures. Returns the number of successful sends.
    """
    from organize.models import NotificationPreference, PushSubscription

    if event not in PUSH_EVENTS:
        return 0
    if not session.effective('push_notifications_enabled'):
        return 0
    user_ids = _recipient_user_ids(session)
    if not user_ids:
        return 0

    preferences = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(user_id__in=user_ids)
    }
    subscriptions = (
        PushSubscription.objects
        .filter(user_id__in=user_ids, revoked_at__isnull=True)
        .select_related('user')
    )

    message = _build_payload(session, event, tower=tower, team=team, payload=payload)
    sender = get_sender()
    sent = 0
    for subscription in subscriptions:
        preference = preferences.get(subscription.user_id)
        if preference is not None and not preference.allows(event):
            continue
        try:
            sender.send(subscription, message)
            sent += 1
        except SubscriptionGone:
            logger.info(
                'Pruning gone push subscription %s (user %s)',
                subscription.pk, subscription.user_id,
            )
            subscription.revoke()
        except Exception:
            logger.warning(
                'Push delivery failed for subscription %s (user %s)',
                subscription.pk, subscription.user_id, exc_info=True,
            )
    return sent
