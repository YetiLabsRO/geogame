import xml.dom.minidom

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from game.models import Challenge, Collection, Tower, Zone


class Command(BaseCommand):
    help = (
        'Import KML geodata into the points repository, grouped into a '
        'named target Collection (created if absent). Re-running for the '
        'same Collection replaces its Zone and Tower data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--collection',
            default='Imported map',
            help='Name of the target Collection the imported Zones and Towers are added to.',
        )

    def _unique_slug(self, name):
        base = slugify(name)[:70] or 'collection'
        slug, counter = base, 2
        while Collection.objects.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        return slug

    def parse_zones(self, doc, zone_type, collection):
        zones = doc.getElementsByTagName("Placemark")
        for zone in zones:
            zone_name = zone.getElementsByTagName("name")[0].firstChild.wholeText
            zone_data = zone.getElementsByTagName("coordinates")[0].firstChild.wholeText.strip()

            poly_data = []
            for line in zone_data.split("\n"):
                point_data = line.strip().split(",")
                poly_data.append((float(point_data[0]), float(point_data[1])))
            zone_obj = Zone.objects.create(
                name=zone_name, shape=Polygon(poly_data), color="000000", scoring_type=zone_type,
            )
            collection.zones.add(zone_obj)

    def handle(self, *args, **options):
        collection_name = options['collection']
        collection = Collection.objects.filter(name=collection_name).first()
        if collection is None:
            collection = Collection.objects.create(
                name=collection_name,
                slug=self._unique_slug(collection_name),
                description='Created by the import_data command.',
            )

        # Idempotent by replacement: recreate this collection's geometry
        # (deleting the Tower rows cascades their tower-bound challenges).
        # Zones go first: the at-least-one-tower-per-zone guard refuses to
        # delete a tower that is a zone's last member, so towers-first
        # cannot replace a collection that has already been imported once.
        Zone.objects.filter(collections=collection).delete()
        Tower.objects.filter(collections=collection).delete()

        doc = xml.dom.minidom.parse(str(settings.BASE_DIR / "game" / "data" / "zone_normal.kml"))
        self.parse_zones(doc, 1, collection)

        doc = xml.dom.minidom.parse(str(settings.BASE_DIR / "game" / "data" / "zone_bonus.kml"))
        self.parse_zones(doc, 4, collection)

        default_zone = collection.zones.order_by('pk').first()

        doc = xml.dom.minidom.parse(str(settings.BASE_DIR / "game" / "data" / "puncte.kml"))
        points = doc.getElementsByTagName("Placemark")
        for point in points:
            point_name = point.getElementsByTagName("name")[0].firstChild.wholeText

            try:
                zone_desc = point.getElementsByTagName("description")[0].firstChild.wholeText
                zone_desc = zone_desc.split("<br>")
            except IndexError:
                zone_desc = []
            point_data = point.getElementsByTagName("coordinates")[0].firstChild.wholeText.strip()
            point_data = point_data.strip().split(",")
            point_data = (float(point_data[0]), float(point_data[1]))
            t = Tower.objects.create(
                name=point_name, location=Point(point_data), category=1,
                is_active=True,
            )
            t.zones.add(default_zone)
            collection.towers.add(t)
            for c in zone_desc:
                Challenge.objects.create(text=c, tower=t, difficulty=1)

        self.stdout.write(
            f'Imported {collection.zones.count()} zones and '
            f'{collection.towers.count()} towers into collection "{collection.name}".'
        )
