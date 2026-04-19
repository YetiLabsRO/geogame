"""Backfill Game.slug from name for existing rows and then tighten to NOT NULL.

Idempotent: if a slug is already set we leave it alone. Collisions are
resolved by appending a numeric suffix.
"""
from django.db import migrations, models
from django.utils.text import slugify


def backfill(apps, schema_editor):
    Game = apps.get_model('organize', 'Game')
    used = set(Game.objects.exclude(slug__isnull=True).values_list('slug', flat=True))
    for game in Game.objects.filter(slug__isnull=True).order_by('id'):
        base = slugify(game.name) or f'game-{game.id}'
        base = base[:60]
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f'{base}-{suffix}'[:64]
            suffix += 1
        used.add(candidate)
        game.slug = candidate
        game.save(update_fields=['slug'])


def reverse(apps, schema_editor):
    # Nothing to do — we never drop the column in the forward migration.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0004_game_config_fields'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
        migrations.AlterField(
            model_name='game',
            name='slug',
            field=models.SlugField(max_length=64, unique=True),
        ),
    ]
