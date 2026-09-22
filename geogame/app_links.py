"""App-link verification documents for the Capacitor mobile shell (mobile-app).

Serves the two "well-known" documents Android and iOS fetch to decide
whether `https://<host>/nfc/*`, `/join/*` and `/invite/*` should open the
installed app instead of the browser fallback page:

- `/.well-known/assetlinks.json` — Android App Links (Digital Asset Links).
- `/.well-known/apple-app-site-association` — iOS Universal Links.

Both are built from `settings.MOBILE_APP_LINKS` and served unauthenticated
(the OS fetches them anonymously). Defaults (empty fingerprint list / no
Apple app id) keep the endpoints live before signing keys and an Apple
Team ID exist — see openspec/changes/mobile-app/design.md decision D7.
"""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def assetlinks(request):
    """GET /.well-known/assetlinks.json — Android Digital Asset Links."""
    links = settings.MOBILE_APP_LINKS
    return JsonResponse(
        [
            {
                'relation': ['delegate_permission/common.handle_all_urls'],
                'target': {
                    'namespace': 'android_app',
                    'package_name': links['android_package'],
                    'sha256_cert_fingerprints': links['android_sha256_fingerprints'],
                },
            },
        ],
        safe=False,
        content_type='application/json',
    )


@require_GET
def apple_app_site_association(request):
    """GET /.well-known/apple-app-site-association — iOS Universal Links.

    Returned even when `apple_app_id` is not configured yet (empty
    `details`), so the endpoint exists ahead of the Apple Team ID.
    """
    links = settings.MOBILE_APP_LINKS
    details = []
    if links['apple_app_id']:
        details.append({
            'appID': links['apple_app_id'],
            'paths': links['paths'],
        })
    return JsonResponse(
        {'applinks': {'apps': [], 'details': details}},
        content_type='application/json',
    )
