# Data migration for the game-lifecycle-states change.
#
# Maps the legacy boolean onto the new state machine so runtime
# behaviour is unchanged:
#   * is_active=True  -> RUNNING
#   * is_active=False -> FINISHED
#   * any Session with an open PauseWindow -> PAUSED (so the
#     "state == PAUSED iff open window" invariant holds immediately).

from django.db import migrations


def backfill_state(apps, schema_editor):
    Session = apps.get_model('organize', 'Session')
    PauseWindow = apps.get_model('game', 'PauseWindow')

    Session.objects.filter(is_active=True).update(state='RUNNING')
    Session.objects.filter(is_active=False).update(state='FINISHED')

    paused_ids = (
        PauseWindow.objects
        .filter(ended_at__isnull=True)
        .values_list('session_id', flat=True)
        .distinct()
    )
    Session.objects.filter(id__in=list(paused_ids)).update(state='PAUSED')


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0011_session_state'),
        ('game', '0021_pausewindow_teamtowerfailcounter'),
    ]

    operations = [
        migrations.RunPython(backfill_state, migrations.RunPython.noop),
    ]
