"""Introduce Session as the runtime entity between Game and Team.

For every existing Game we create a default Session that inherits the
Game's dates and is_active flag, then re-parent every Team on that
Game onto the default Session. Team.game is dropped once the backfill
completes.

Team.group ChainedForeignKey becomes a plain ForeignKey in the same
migration: with Team.game gone, the single-hop chain that smart_selects
used can no longer reach TeamGroup via Game. Admin forms will show the
full group list instead.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def reparent_teams(apps, schema_editor):
    Game = apps.get_model('organize', 'Game')
    Session = apps.get_model('organize', 'Session')
    Team = apps.get_model('organize', 'Team')

    for game in Game.objects.all():
        session = Session.objects.filter(game=game, slug='default').first()
        if session is None:
            session = Session.objects.create(
                game=game,
                slug='default',
                name='Default session',
                start_time=game.start_time,
                end_time=game.end_time,
                is_active=game.is_active,
            )
        Team.objects.filter(game=game, session__isnull=True).update(
            session=session,
        )


def reverse(apps, schema_editor):
    # Best-effort: push Teams back onto the Game derived from their
    # Session, then drop the Sessions we created. The reverse path is
    # provided to satisfy RunPython; production rollbacks should use a
    # schema snapshot instead.
    Team = apps.get_model('organize', 'Team')
    Session = apps.get_model('organize', 'Session')
    for team in Team.objects.select_related('session').all():
        team.game_id = team.session.game_id
        team.save(update_fields=['game_id'])
    Session.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0005_backfill_game_slug'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Create the Session model.
        migrations.CreateModel(
            name='Session',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('slug', models.SlugField(max_length=64)),
                ('name', models.CharField(max_length=255)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('is_active', models.BooleanField(default=False)),
                (
                    'created_at',
                    models.DateTimeField(auto_now_add=True, null=True),
                ),
                (
                    'game',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='sessions',
                        to='organize.game',
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='sessions_created',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'unique_together': {('game', 'slug')},
            },
        ),
        # 2. Drop smart_selects chaining metadata (plain FK).
        migrations.AlterField(
            model_name='team',
            name='group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='organize.teamgroup',
            ),
        ),
        # 3. Add the new Team.session FK (nullable during backfill).
        migrations.AddField(
            model_name='team',
            name='session',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='teams',
                to='organize.session',
            ),
        ),
        # 4. Backfill.
        migrations.RunPython(reparent_teams, reverse),
        # 5. Tighten session to NOT NULL and drop the legacy game FK.
        migrations.AlterField(
            model_name='team',
            name='session',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='teams',
                to='organize.session',
            ),
        ),
        migrations.RemoveField(
            model_name='team',
            name='game',
        ),
    ]
