# Data migration for the points-repository-and-collections change.
#
# For every existing Game create one Collection named '<game name> map'
# holding exactly that Game's current Towers and Zones (via the legacy
# Tower.game / Zone.game FKs), and link the Collection to the Game.
# After this migration every Session resolves the identical geometry it
# did before, but through Game.collections instead of the direct FKs
# (which 0024 removes).

from django.db import migrations
from django.utils.text import slugify


def _unique_slug(collection_model, name):
    base = slugify(name)[:70] or 'collection'
    slug, counter = base, 2
    while collection_model.objects.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


def create_collections(apps, schema_editor):
    Game = apps.get_model('organize', 'Game')
    Collection = apps.get_model('game', 'Collection')
    Tower = apps.get_model('game', 'Tower')
    Zone = apps.get_model('game', 'Zone')

    for game in Game.objects.all():
        name = f'{game.name} map'
        collection = Collection.objects.create(
            name=name,
            slug=_unique_slug(Collection, name),
            description=f'Auto-created from the map of game "{game.name}".',
            created_by_id=game.created_by_id,
        )
        collection.towers.set(Tower.objects.filter(game=game))
        collection.zones.set(Zone.objects.filter(game=game))
        game.collections.add(collection)


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0022_collection'),
        ('organize', '0011_game_collections_roles_cloning'),
    ]

    operations = [
        migrations.RunPython(create_collections, migrations.RunPython.noop),
    ]
