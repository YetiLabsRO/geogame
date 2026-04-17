import xml.dom.minidom

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand

from game.models import *


class Command(BaseCommand):
    help = 'Import geodata for Cercetador'

    def parse_zones(self, doc, zone_type):
        zones = doc.getElementsByTagName("Placemark")
        for zone in zones:
            zone_name = zone.getElementsByTagName("name")[0].firstChild.wholeText
            zone_data = zone.getElementsByTagName("coordinates")[0].firstChild.wholeText.strip()

            poly_data = []
            for line in zone_data.split("\n"):
                point_data = line.strip().split(",")
                poly_data.append((float(point_data[0]), float(point_data[1])))
            Zone.objects.create(name=zone_name, shape=Polygon(poly_data), color="000000", scoring_type=zone_type)

    def handle(self, *args, **options):
        Zone.objects.all().delete()
        Tower.objects.all().delete()
        Challenge.objects.all().delete()

        doc = xml.dom.minidom.parse(str(settings.BASE_DIR / "game" / "data" / "zone_normal.kml"))
        self.parse_zones(doc, 1)

        doc = xml.dom.minidom.parse(str(settings.BASE_DIR / "game" / "data" / "zone_bonus.kml"))
        self.parse_zones(doc, 4)

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
            t = Tower.objects.create(name=point_name, location=Point(point_data), category=1, zone=Zone.objects.all().first(), is_active=True)
            for c in zone_desc:
                Challenge.objects.create(text=c, tower=t, difficulty=1)


