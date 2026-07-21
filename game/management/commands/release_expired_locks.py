"""Sweep expired TowerLocks (tower-locking §4.2).

Stamps `released_at` / `release_reason=EXPIRED` on every un-released
lock whose finish deadline has passed. Idempotent — safe to run from
cron / a periodic scheduler at any frequency. Lock READS already treat
lapsed locks as free (lazy expiry), so this sweep is a tidy-up that
keeps the table from accumulating phantom "active" rows, never a
correctness dependency.
"""
from django.core.management.base import BaseCommand

from game.models import TowerLock


class Command(BaseCommand):
    help = 'Release expired tower locks (release_reason=EXPIRED). Idempotent.'

    def handle(self, *args, **options):
        released = TowerLock.sweep_expired()
        self.stdout.write(self.style.SUCCESS(f'Released {released} expired lock(s).'))
