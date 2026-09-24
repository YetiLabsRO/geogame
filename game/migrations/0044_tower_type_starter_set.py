"""A starting vocabulary of Tower types, for an install that has none.

Without this, a fresh install ships zero types and the first curator to
open field mode has to invent a taxonomy before they can type their
first tower. These seven are the kinds of place a town actually gets
scouted for; they are a *starting point*, editable and removable from
the tower-types manager like any other row.

**Only into an empty table.** An install that has built its own
vocabulary must never have this one appended to it or merged into it —
a migration that adds rows to a populated table would, on every deploy
that has ever run it, look like someone else editing your library. The
emptiness check is the whole safety property, and the reverse removes
only the rows this created, by slug, so a curator's own "Fountain" is
not taken away with ours.
"""
from django.db import migrations

# (slug, name, icon, colour, capture radius in metres or None)
#
# Radii: a statue or a fountain is a thing you stand next to, so the
# radius is tight. A square is somewhere you stand *in*, so it is wide
# enough that standing anywhere sensible in it counts. Untyped towers,
# and types left at None, fall back to the Game's own radius.
STARTER_TYPES = [
    ('building', 'Building', 'bi-building', '#7A5C3E', 30),
    ('place', 'Place', 'bi-geo-alt-fill', '#5F6B7A', None),
    ('square', 'Square', 'bi-signpost-2-fill', '#B8860B', 45),
    ('statue', 'Statue', 'bi-person-standing', '#6C757D', 20),
    ('art-installation', 'Art installation', 'bi-palette-fill', '#C2185B', 20),
    ('fountain', 'Fountain', 'bi-droplet-fill', '#1F6FEB', 25),
    ('church', 'Church', 'bi-bank', '#8E44AD', 40),
]


def seed_starter_types(apps, schema_editor):
    TowerType = apps.get_model('game', 'TowerType')
    if TowerType.objects.exists():
        return
    TowerType.objects.bulk_create([
        TowerType(
            slug=slug,
            name=name,
            icon=icon,
            color=color,
            proximity_meters=radius,
            order=index,
        )
        for index, (slug, name, icon, color, radius) in enumerate(STARTER_TYPES)
    ])


def remove_starter_types(apps, schema_editor):
    """Take back only what was seeded, and only if it is untouched.

    A type that has been renamed, restyled or attached to towers is the
    curator's now, whatever its slug says, so it stays.
    """
    TowerType = apps.get_model('game', 'TowerType')
    for slug, name, icon, color, radius in STARTER_TYPES:
        TowerType.objects.filter(
            slug=slug,
            name=name,
            icon=icon,
            color=color,
            proximity_meters=radius,
            towers__isnull=True,
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0043_media_assets'),
    ]

    operations = [
        migrations.RunPython(seed_starter_types, remove_starter_types),
    ]
