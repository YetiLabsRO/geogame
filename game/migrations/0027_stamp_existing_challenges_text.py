# challenge-type-system: explicit, idempotent stamp of every existing
# Challenge as TEXT. The column default already applies TEXT to
# pre-existing rows when 0026 adds the column; this migration makes the
# invariant explicit and repairs any row that somehow carries an empty
# or NULL type, so pre-change challenges behave byte-for-byte as before.
from django.db import migrations
from django.db.models import Q


def stamp_text(apps, schema_editor):
    Challenge = apps.get_model('game', 'Challenge')
    Challenge.objects.filter(
        Q(type__isnull=True) | Q(type=''),
    ).update(type='TEXT')


def noop(apps, schema_editor):
    # Reverse is a no-op: TEXT rows are the pre-change shape.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0026_challenge_type_system'),
    ]

    operations = [
        migrations.RunPython(stamp_text, noop),
    ]
