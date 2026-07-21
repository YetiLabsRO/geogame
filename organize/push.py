"""Opt-in push notification delivery (realtime-and-notifications).

Push is advisory and best-effort: the in-app websocket / polling path
stays authoritative, and nothing in gameplay depends on a notification
arriving. A notification goes out only when EVERY gate passes:

1. the Session's effective ``push_notifications_enabled`` is True
   (Game default False, per-Session override);
2. the recipient has an active (non-revoked) ``PushSubscription`` —
   the explicit consent artifact;
3. the recipient's ``NotificationPreference`` master flag and the
   per-event toggle (steal / conquer / bonus) allow it.

Senders sit behind a tiny interface so tests inject a stub and the app
never hard-depends on delivery infrastructure:

- ``WebPushSender`` (pywebpush + VAPID) is used only when VAPID keys are
  configured via settings/env;
- otherwise ``LoggingPushSender`` logs what WOULD be sent and delivers
  nothing. FCM subscriptions are likewise logged-only until an FCM
  sender is configured (``FCM_SERVER_KEY`` reserved for it).

A sender signals a dead endpoint by raising ``SubscriptionGone`` (push
service answered 404/410); the subscription is then pruned (revoked) and
never sent to again.
"""

import json
import logging

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
    """Real Web Push delivery via pywebpush + VAPID keys from settings."""

    def send(self, subscription, payload):
        from pywebpush import WebPushException, webpush

        if subscription.kind != subscription.KIND_WEBPUSH:
            # FCM delivery is not implemented yet; log-only.
            LoggingPushSender().send(subscription, payload)
            return
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


def get_sender():
    """The active sender: real Web Push when VAPID keys exist, else the stub.

    Resolved per call so tests can patch this function (or the settings)
    without import-order concerns.
    """
    if settings.WEBPUSH_VAPID_PRIVATE_KEY and settings.WEBPUSH_VAPID_PUBLIC_KEY:
        return WebPushSender()
    return LoggingPushSender()


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
