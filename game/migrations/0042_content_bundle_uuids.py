"""Portable identity for the models that travel in a content bundle.

Added in three steps per model rather than one. `AddField` evaluates a
callable default ONCE and writes that single value into every existing
row, so a one-step add of a unique column fails on any non-empty table.
The column therefore arrives nullable and with no default at all, every
existing row is then given its own value, and only then is the unique
constraint applied.
"""
import uuid

from django.db import migrations, models

MODELS = [
    ('towertype', 'TowerType'),
    ('zone', 'Zone'),
    ('tower', 'Tower'),
    ('towerphoto', 'TowerPhoto'),
    ('collection', 'Collection'),
    ('presencerequirement', 'PresenceRequirement'),
    ('challenge', 'Challenge'),
    ('scoremultiplier', 'ScoreMultiplier'),
    ('trail', 'Trail'),
    ('trailstep', 'TrailStep'),
    ('trailedge', 'TrailEdge'),
]


def backfill(apps, schema_editor):
    for lowercase, name in MODELS:
        model = apps.get_model('game', name)
        rows = model.objects.filter(uuid__isnull=True).only('pk')
        for row in rows.iterator(chunk_size=500):
            model.objects.filter(pk=row.pk).update(uuid=uuid.uuid4())


def noop(apps, schema_editor):
    """Reverse is a no-op: the columns go away with the AddFields."""


def _add(lowercase):
    return migrations.AddField(
        model_name=lowercase,
        name='uuid',
        field=models.UUIDField(editable=False, null=True),
    )


def _tighten(lowercase):
    return migrations.AlterField(
        model_name=lowercase,
        name='uuid',
        field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0041_towertype_tower_color_tower_icon_tower_tower_type'),
    ]

    operations = (
        [_add(lowercase) for lowercase, _ in MODELS]
        + [migrations.RunPython(backfill, noop)]
        + [_tighten(lowercase) for lowercase, _ in MODELS]
    )
