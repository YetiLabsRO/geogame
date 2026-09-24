"""The repository as one map-ready feed (library-map capability).

Collections are how a curator turns a pile of places into a map a game
can use, and curating them through lists of names cannot answer the
questions actually being asked — do these belong together, is this one
an outlier, does this zone contain those towers. Those are spatial
questions, so the library is drawn.

Drawing it needs every element, its styling, and which Collections hold
it, all at once: a map that fetches per element is a map that takes a
minute to appear and hammers the server doing it. Hence one response.

Scale, stated rather than pretended away: this is right for a repository
of hundreds and wrong for one of tens of thousands. The shape is such
that a bounding-box or updated-since filter can be added later without
changing what a caller does with the response.
"""

from django.db.models import Count
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game.models import Collection, Tower, TowerType, Zone


def _towers():
    rows = (
        Tower.objects
        .select_related('tower_type')
        .prefetch_related('collections')
        .annotate(media_count=Count('photos', distinct=True))
        .order_by('name')
    )
    return [{
        'id': tower.id,
        'name': tower.name,
        'lat': tower.location.y if tower.location else None,
        'lng': tower.location.x if tower.location else None,
        'is_active': tower.is_active,
        'tower_type': tower.tower_type_id,
        'tower_type_name': tower.tower_type.name if tower.tower_type else None,
        # Resolved server-side; a client draws from these and never
        # re-implements tower-over-type-over-default.
        'icon': tower.resolved_icon,
        'color': tower.resolved_color,
        'media_count': tower.media_count,
        # Membership rides along per element rather than per collection.
        # It inverts where membership is stored, and it is what lets the
        # map answer "is this one in?" for every pin without a second
        # lookup.
        'collection_ids': [c.id for c in tower.collections.all()],
    } for tower in rows]


def _zones():
    rows = Zone.objects.prefetch_related('collections').order_by('name')
    return [{
        'id': zone.id,
        'name': zone.name,
        'color': zone.color,
        'shape': zone.shape.geojson if zone.shape else None,
        # Zones cannot carry media yet — that arrives with
        # `tower-zone-media`. Zero here is true, not a placeholder.
        'media_count': 0,
        'collection_ids': [c.id for c in zone.collections.all()],
    } for zone in rows]


class StaffLibraryView(APIView):
    """Every repository element, drawable in one request."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        collections = Collection.objects.annotate(
            tower_total=Count('towers', distinct=True),
            zone_total=Count('zones', distinct=True),
        ).order_by('name')
        return Response({
            'towers': _towers(),
            'zones': _zones(),
            'collections': [{
                'id': c.id,
                'name': c.name,
                'slug': c.slug,
                'tower_count': c.tower_total,
                'zone_count': c.zone_total,
            } for c in collections],
            'tower_types': [{
                'id': t.id,
                'name': t.name,
                'slug': t.slug,
                'icon': t.icon,
                'color': t.color,
            } for t in TowerType.objects.all()],
        })
