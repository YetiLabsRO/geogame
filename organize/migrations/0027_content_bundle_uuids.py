"""Portable identity for Game, GameRole and TeamGroup (content-bundles).

Three steps for the same reason as `game.0042_content_bundle_uuids`:
`AddField` evaluates a callable default once and writes that one value
into every existing row, which cannot then be made unique.
"""
import uuid

from django.db import migrations, models


MODELS = [
    ('game', 'Game'),
    ('gamerole', 'GameRole'),
    ('teamgroup', 'TeamGroup'),
]


def backfill(apps, schema_editor):
    for lowercase, name in MODELS:
        model = apps.get_model('organize', name)
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
        ('organize', '0026_merge_20260721_1415'),
    ]

    operations = (
        [_add(lowercase) for lowercase, _ in MODELS]
        + [migrations.RunPython(backfill, noop)]
        + [_tighten(lowercase) for lowercase, _ in MODELS]
    )
