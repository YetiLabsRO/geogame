"""Staff endpoints for content bundles (content-bundles capability).

Three POSTs: export a selection as a download, inspect an uploaded
bundle without touching anything, and import one. Export is a POST
rather than a GET because the selection is two lists of ids, and a
fifty-item selection does not belong in a URL.
"""
from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from game import bundles
from game.models import Collection
from organize.models import Game

# An uploaded bundle is read entirely before anything is written, so the
# ceiling here is about memory, not about trust; the archive reader
# applies its own limits to what the zip expands to.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def _ids(request, key):
    values = request.data.get(key) or []
    if not isinstance(values, list):
        return None
    out = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            return None
    return out


class StaffBundleExportView(APIView):
    """POST a selection of game and collection ids; get a bundle back."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        game_ids = _ids(request, 'games')
        collection_ids = _ids(request, 'collections')
        if game_ids is None or collection_ids is None:
            return Response(
                {'detail': '`games` and `collections` must be lists of ids.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not game_ids and not collection_ids:
            return Response(
                {'detail': 'Select at least one game or collection.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        games = list(Game.objects.filter(pk__in=game_ids))
        collections = list(Collection.objects.filter(pk__in=collection_ids))
        missing = (set(game_ids) - {g.pk for g in games}) | (
            set(collection_ids) - {c.pk for c in collections}
        )
        if missing:
            return Response(
                {'detail': f'Unknown id(s): {sorted(missing)}.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        buffer, payload = bundles.export_bundle(games=games, collections=collections)
        filename = _filename(payload)
        response = HttpResponse(
            buffer.getvalue(), content_type='application/zip',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        # So a browser download can still show what it got without
        # re-parsing the zip it has just been handed.
        response['X-Bundle-Counts'] = ','.join(
            f'{key}={len(rows)}' for key, rows in payload['content'].items()
        )
        return response


def _filename(payload):
    selection = payload.get('selection', {})
    stem = (selection.get('games') or selection.get('collections') or ['content'])[0]
    date = (payload.get('exported_at') or '')[:10]
    return f'{stem}-{date}.zip' if date else f'{stem}.zip'


class _UploadedBundleView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _open(self, request):
        """Return (bundle, error_response). Exactly one is not None."""
        upload = request.data.get('file')
        if upload is None:
            return None, Response(
                {'detail': 'Attach the bundle as `file`.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        size = getattr(upload, 'size', None)
        if size is not None and size > MAX_UPLOAD_BYTES:
            return None, Response(
                {'detail': f'Bundle is larger than {MAX_UPLOAD_BYTES} bytes.'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        try:
            return bundles.read_bundle(upload), None
        except bundles.BundleError as exc:
            return None, Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )

    def _mode(self, request):
        mode = request.data.get('mode') or bundles.MODE_SYNC
        return mode if mode in bundles.MODES else None


class StaffBundleInspectView(_UploadedBundleView):
    """What an uploaded bundle holds, and what importing it would do."""

    def post(self, request):
        mode = self._mode(request)
        if mode is None:
            return Response(
                {'detail': f'`mode` must be one of {list(bundles.MODES)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        bundle, error = self._open(request)
        if error is not None:
            return error
        with bundle:
            return Response(bundles.inspect_bundle(bundle, mode=mode))


class StaffBundleImportView(_UploadedBundleView):
    """Apply an uploaded bundle."""

    def post(self, request):
        mode = self._mode(request)
        if mode is None:
            return Response(
                {'detail': f'`mode` must be one of {list(bundles.MODES)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        bundle, error = self._open(request)
        if error is not None:
            return error
        with bundle:
            try:
                report = bundles.import_bundle(bundle, mode=mode)
            except bundles.BundleError as exc:
                return Response(
                    {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(report.as_dict())
