"""Denormalize Game onto TeamMembership to enforce one-session-per-game.

Adds the column nullable, backfills from team.session.game, tightens
the constraint, then adds the conditional unique(user, game) where
is_active=True constraint.
"""
import django.db.models.deletion
from django.db import migrations, models


def backfill(apps, schema_editor):
    TeamMembership = apps.get_model('organize', 'TeamMembership')
    for membership in TeamMembership.objects.select_related(
        'team__session',
    ).all():
        membership.game_id = membership.team.session.game_id
        membership.save(update_fields=['game'])


def reverse(apps, schema_editor):
    # Nothing to do in reverse — the column will be dropped.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0007_current_session'),
    ]

    operations = [
        migrations.AddField(
            model_name='teammembership',
            name='game',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='memberships',
                to='organize.game',
            ),
        ),
        migrations.RunPython(backfill, reverse),
        migrations.AlterField(
            model_name='teammembership',
            name='game',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='memberships',
                to='organize.game',
            ),
        ),
        migrations.AddConstraint(
            model_name='teammembership',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)),
                fields=('user', 'game'),
                name='unique_active_membership_per_game',
            ),
        ),
    ]
