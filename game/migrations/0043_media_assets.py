"""Reference media widens from tower photos to media on towers and zones.

Three operations in one migration, because they are one change: the new
table, the rows carried across, and the old table removed. Splitting
them would leave a release in which both exist and either could be
written to.

The carry-over copies `TowerPhoto.image.name` — the stored relative
path — straight into `MediaAsset.file`. **No file is moved.** A
`FileField` holds a path, so the old `tower_photos/...` entries keep
resolving on the same storage; re-homing them would mean copying every
file for no benefit and a window in which half of them are missing. New
captures land under `reference_media/`, and the two prefixes coexist
without anything needing to know.

The `uuid` travels too. It is the portable identity content bundles use,
and a bundle exported before this migration has to still name the same
row after it.
"""
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import game.models


def carry_over_tower_photos(apps, schema_editor):
    """Every reference photo becomes image media on the same tower."""
    TowerPhoto = apps.get_model('game', 'TowerPhoto')
    MediaAsset = apps.get_model('game', 'MediaAsset')
    MediaAsset.objects.bulk_create(
        [
            MediaAsset(
                uuid=photo.uuid,
                tower_id=photo.tower_id,
                zone=None,
                kind='IMAGE',
                # `.name` is the stored path; reading it touches no storage.
                file=photo.image.name,
                caption=photo.caption,
                duration_seconds=None,
                # 0 means "never measured" — see `MediaAsset.byte_size`.
                # Stat-ing several hundred files to fill in a number
                # nothing enforces retrospectively is not worth the
                # round trips on remote storage.
                byte_size=0,
                captured_by_id=photo.captured_by_id,
                captured_at=photo.captured_at,
            )
            for photo in TowerPhoto.objects.all().iterator()
        ],
        batch_size=500,
    )


def restore_tower_photos(apps, schema_editor):
    """Back to tower photos, for the images that were ever expressible as one.

    Audio, video and anything attached to a zone has no representation
    in `TowerPhoto` and is dropped. That is the honest reverse of this
    change rather than a failure of it: going back means going back to a
    model that could not hold them.
    """
    TowerPhoto = apps.get_model('game', 'TowerPhoto')
    MediaAsset = apps.get_model('game', 'MediaAsset')
    assets = list(
        MediaAsset.objects.filter(kind='IMAGE', tower__isnull=False)
        .order_by('pk'),
    )
    restored = TowerPhoto.objects.bulk_create([
        TowerPhoto(
            uuid=asset.uuid,
            tower_id=asset.tower_id,
            image=asset.file.name,
            caption=asset.caption,
            captured_by_id=asset.captured_by_id,
        )
        for asset in assets
    ])
    # `TowerPhoto.captured_at` is `auto_now_add`, so the create above
    # stamped every row with the moment of the rollback. Put the real
    # capture times back.
    for photo, asset in zip(restored, assets):
        photo.captured_at = asset.captured_at
    if restored:
        TowerPhoto.objects.bulk_update(restored, ['captured_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0042_content_bundle_uuids'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MediaAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('kind', models.CharField(choices=[('IMAGE', 'Photo'), ('AUDIO', 'Audio note'), ('VIDEO', 'Video clip')], default='IMAGE', max_length=8)),
                ('file', models.FileField(upload_to=game.models.media_upload_to)),
                ('caption', models.CharField(blank=True, default='', max_length=255)),
                ('duration_seconds', models.FloatField(blank=True, null=True)),
                ('byte_size', models.PositiveBigIntegerField(default=0)),
                ('captured_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('captured_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='captured_media', to=settings.AUTH_USER_MODEL)),
                ('tower', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='media', to='game.tower')),
                ('zone', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='media', to='game.zone')),
            ],
            options={
                'ordering': ['-captured_at', '-id'],
            },
        ),
        # Before the data moves, not after: the carry-over is then
        # checked by the same rule every later write is, rather than
        # being the one insert that got in unexamined.
        migrations.AddConstraint(
            model_name='mediaasset',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(('tower__isnull', False), ('zone__isnull', True)),
                    models.Q(('tower__isnull', True), ('zone__isnull', False)),
                    _connector='OR',
                ),
                name='media_asset_exactly_one_subject',
            ),
        ),
        migrations.RunPython(carry_over_tower_photos, restore_tower_photos),
        migrations.DeleteModel(
            name='TowerPhoto',
        ),
    ]
