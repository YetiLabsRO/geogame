"""Purge LocationPing rows per retention + consent (live-location).

Schedulable (cron) command enforcing the two privacy bounds of the
live-location capability:

1. Retention: pings older than their Session's effective
   `location_retention_days` are deleted. Finishing/deactivating a
   Session does NOT purge its pings — history stays available for
   analysis until the retention window expires.
2. Consent: any ping whose user no longer holds standing consent for
   the Session (withdrawn, or the row vanished) is deleted. Withdrawal
   already purges synchronously; this is the safety-net re-sweep.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from game.models import LocationConsent, LocationPing
from organize.models import Session


class Command(BaseCommand):
    help = 'Delete location pings past retention or without standing consent.'

    def handle(self, *args, **options):
        now = timezone.now()
        expired_total = 0
        unconsented_total = 0

        session_ids = (
            LocationPing.objects.values_list('session_id', flat=True).distinct()
        )
        for session in Session.objects.filter(id__in=list(session_ids)):
            retention_days = session.effective('location_retention_days')
            cutoff = now - timedelta(days=retention_days)
            expired, _ = LocationPing.objects.filter(
                session=session, recorded_at__lt=cutoff,
            ).delete()
            expired_total += expired

            standing = LocationConsent.objects.filter(
                session=session, withdrawn_at__isnull=True,
            ).values_list('user_id', flat=True)
            unconsented, _ = (
                LocationPing.objects
                .filter(session=session)
                .exclude(user_id__in=standing)
                .delete()
            )
            unconsented_total += unconsented

        if options.get('verbosity', 1):
            self.stdout.write(
                self.style.SUCCESS(
                    f'Purged {expired_total} expired ping(s) and '
                    f'{unconsented_total} without standing consent.',
                ),
            )
