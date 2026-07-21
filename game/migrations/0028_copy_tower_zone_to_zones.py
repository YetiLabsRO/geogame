# Data migration (tower-zone-topology, task 2.1): copy each Tower's
# legacy single `zone` FK into one row of the new `zones` many-to-many,
# then report (never delete) any Zone left with zero member towers so
# staff can attach a tower or remove the zone deliberately.

from django.db import migrations


def copy_zone_fk_to_m2m(apps, schema_editor):
    Tower = apps.get_model('game', 'Tower')
    Zone = apps.get_model('game', 'Zone')
    Through = Tower.zones.through

    links = [
        Through(tower_id=tower_id, zone_id=zone_id)
        for tower_id, zone_id in Tower.objects
        .filter(zone__isnull=False)
        .values_list('pk', 'zone_id')
    ]
    Through.objects.bulk_create(links, ignore_conflicts=True)

    empty_zones = Zone.objects.filter(towers__isnull=True).order_by('pk')
    for zone in empty_zones:
        print(
            f'[tower-zone-topology] Zone #{zone.pk} "{zone.name}" has no '
            f'member towers after migration; attach a tower or remove it.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0027_tower_zones_m2m'),
    ]

    operations = [
        migrations.RunPython(copy_zone_fk_to_m2m, migrations.RunPython.noop),
    ]
