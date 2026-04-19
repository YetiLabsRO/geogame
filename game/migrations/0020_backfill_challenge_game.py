"""Backfill Challenge.game for existing rows.

For challenges bound to a Tower, use tower.game. For generic challenges
(tower=NULL), attach them to the first (oldest) Game — the common case
in the pre-Phase-3 world is a single monolithic Game, and any ambiguity
left over will be surfaced by staff touching the challenge management
UI once T3.5 scoping lands.

Challenge.game stays nullable at the DB layer through Phase 3; the
non-null constraint is applied in a later phase once the Game↔Session
refactor has settled.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Challenge = apps.get_model('game', 'Challenge')
    Game = apps.get_model('organize', 'Game')
    default_game = Game.objects.order_by('id').first()

    for challenge in Challenge.objects.filter(game__isnull=True).select_related('tower'):
        if challenge.tower_id is not None and challenge.tower.game_id is not None:
            challenge.game_id = challenge.tower.game_id
        elif default_game is not None:
            challenge.game_id = default_game.id
        else:
            # No games exist — nothing to attach this challenge to. Leave
            # game NULL; this only happens in pristine test databases that
            # have no Game rows, where the data migration is effectively a
            # no-op.
            continue
        challenge.save(update_fields=['game'])


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0019_challenge_game'),
        ('organize', '0005_backfill_game_slug'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
