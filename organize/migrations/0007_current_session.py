"""Rotate UserProfile scope to Session + drop transitional Game dates.

- Adds UserProfile.current_session (nullable), backfills it from
  current_game via the game's default Session, then drops current_game.
- Removes Game.start_time and Game.end_time now that the dates live on
  Session. (The T3.2 backfill already copied them over.)
"""
import django.db.models.deletion
from django.db import migrations, models


def backfill(apps, schema_editor):
    UserProfile = apps.get_model('organize', 'UserProfile')
    Session = apps.get_model('organize', 'Session')

    for profile in UserProfile.objects.filter(current_game__isnull=False):
        session = (
            Session.objects
            .filter(game=profile.current_game, slug='default')
            .first()
        )
        if session is None:
            # No default session exists (pathological); pick any session
            # on the game instead, or leave null.
            session = (
                Session.objects.filter(game=profile.current_game).first()
            )
        if session is not None:
            profile.current_session_id = session.id
            profile.save(update_fields=['current_session'])


def reverse(apps, schema_editor):
    UserProfile = apps.get_model('organize', 'UserProfile')
    for profile in UserProfile.objects.filter(current_session__isnull=False):
        profile.current_game_id = profile.current_session.game_id
        profile.save(update_fields=['current_game'])


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0006_session_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='current_session',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='organize.session',
            ),
        ),
        migrations.RunPython(backfill, reverse),
        migrations.RemoveField(
            model_name='userprofile',
            name='current_game',
        ),
        migrations.RemoveField(
            model_name='game',
            name='start_time',
        ),
        migrations.RemoveField(
            model_name='game',
            name='end_time',
        ),
    ]
