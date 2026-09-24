"""Rejoin the two 0040s: challenge media, and the session overview line.

`challenge-media` and the reference-media work were written in parallel
from the same parent, so each app-numbered its migration 0040 and the
graph grew two leaves. Nothing in either touches the other — one creates
a `ChallengeMedia` table, the other's line ends in a `MediaAsset` table
and a seeded vocabulary — so this merges the graph rather than
renumbering, which would strand any database that had already applied
`0040_challengemedia`.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0040_challengemedia'),
        ('game', '0044_tower_type_starter_set'),
    ]

    operations = [
    ]
