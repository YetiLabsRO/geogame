"""REST endpoints for push subscriptions + preferences.

Mounted under /api/push/ (see organize/urls.py):

- ``POST   /api/push/subscriptions/`` — register (consent) a Web Push or
  FCM subscription for the caller; idempotent per endpoint/token.
- ``DELETE /api/push/subscriptions/`` — revoke; a body/query `endpoint`
  (or `fcm_token`) revokes that one subscription, otherwise every
  active subscription of the caller is revoked.
- ``GET/PATCH /api/push/preferences/`` — per-event notification toggles.
- ``GET /api/push/vapid-key/`` — the public VAPID key (public material;
  empty when Web Push is not configured, so clients skip subscribing).
"""

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organize.models import NotificationPreference, PushSubscription


class PushSubscriptionSerializer(serializers.Serializer):
    """Accepts the browser PushSubscription JSON shape, or an FCM token."""

    endpoint = serializers.CharField(required=False, allow_blank=True)
    keys = serializers.DictField(
        child=serializers.CharField(), required=False,
    )
    fcm_token = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        endpoint = attrs.get('endpoint') or ''
        fcm_token = attrs.get('fcm_token') or ''
        if not endpoint and not fcm_token:
            raise serializers.ValidationError(
                'Provide a Web Push `endpoint` (+`keys`) or an `fcm_token`.',
            )
        if endpoint:
            keys = attrs.get('keys') or {}
            if not keys.get('p256dh') or not keys.get('auth'):
                raise serializers.ValidationError(
                    'Web Push subscriptions need `keys.p256dh` and `keys.auth`.',
                )
        return attrs


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ('enabled', 'notify_steal', 'notify_conquer', 'notify_bonus')


def _subscription_payload(subscription):
    return {
        'id': subscription.id,
        'kind': subscription.kind,
        'endpoint': subscription.endpoint,
        'created_at': subscription.created_at,
        'active': subscription.is_active,
    }


class PushSubscriptionView(APIView):
    """Register (POST) / revoke (DELETE) the caller's push subscriptions."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List the caller's active subscriptions (for the settings UI)."""
        subscriptions = request.user.push_subscriptions.filter(
            revoked_at__isnull=True,
        )
        return Response([_subscription_payload(s) for s in subscriptions])

    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        endpoint = data.get('endpoint') or ''
        fcm_token = data.get('fcm_token') or ''
        keys = data.get('keys') or {}

        if endpoint:
            lookup = {'kind': PushSubscription.KIND_WEBPUSH, 'endpoint': endpoint}
            defaults = {
                'p256dh': keys.get('p256dh', ''),
                'auth': keys.get('auth', ''),
                'revoked_at': None,
            }
        else:
            lookup = {'kind': PushSubscription.KIND_FCM, 'fcm_token': fcm_token}
            defaults = {'revoked_at': None}

        subscription, created = PushSubscription.objects.update_or_create(
            user=request.user, **lookup, defaults=defaults,
        )
        return Response(
            _subscription_payload(subscription),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        subscriptions = request.user.push_subscriptions.filter(
            revoked_at__isnull=True,
        )
        endpoint = (
            request.data.get('endpoint')
            if isinstance(request.data, dict) else None
        ) or request.query_params.get('endpoint')
        fcm_token = (
            request.data.get('fcm_token')
            if isinstance(request.data, dict) else None
        ) or request.query_params.get('fcm_token')
        if endpoint:
            subscriptions = subscriptions.filter(endpoint=endpoint)
        elif fcm_token:
            subscriptions = subscriptions.filter(fcm_token=fcm_token)
        revoked = subscriptions.update(revoked_at=timezone.now())
        return Response(
            {'revoked': revoked}, status=status.HTTP_200_OK,
        )


class PushPreferencesView(APIView):
    """Read / update the caller's notification preference toggles."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference = NotificationPreference.for_user(request.user)
        return Response(NotificationPreferenceSerializer(preference).data)

    def patch(self, request):
        preference = NotificationPreference.for_user(request.user)
        serializer = NotificationPreferenceSerializer(
            preference, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def vapid_key(request):
    """Public VAPID key for browser PushManager.subscribe()."""
    return Response({'public_key': settings.WEBPUSH_VAPID_PUBLIC_KEY or None})
