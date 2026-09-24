"""Uploading, listing and removing reference media (tower-zone-media).

One serializer and one viewset mixin serve both subjects. The subject
is the only thing that differs between a tower's media and a zone's, so
it is a class attribute rather than a second copy of the endpoint —
which is the same reasoning that made `MediaAsset` one model with two
nullable subjects instead of two parallel models.
"""
import base64
import binascii
import uuid

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from game.media import (
    MediaRejected,
    check_duration,
    check_kind,
    check_size,
    content_type_for_name,
    extension_for,
    kind_for_content_type,
    normalize_content_type,
)
from game.models import MediaAsset


class Base64MediaField(serializers.FileField):
    """A file that arrives either as multipart or as a base64 data URL.

    The offline queue replays a capture as JSON — there is no multipart
    body to replay, because the capture happened hours earlier in a
    field with no signal — so both shapes have to work through the same
    endpoint.

    The data URL's declared type is kept on the decoded file, because it
    is the only evidence of what was captured: a decoded blob has no
    filename to guess from, and sniffing a container format is a job for
    something that is not us.
    """

    def to_internal_value(self, data):
        if isinstance(data, str):
            content_type = None
            payload = data
            if ';base64,' in data:
                header, payload = data.split(';base64,', 1)
                if header.startswith('data:'):
                    content_type = normalize_content_type(header[len('data:'):])
            try:
                decoded = base64.b64decode(payload)
            except (TypeError, ValueError, binascii.Error):
                raise serializers.ValidationError(
                    'The uploaded media could not be decoded.',
                )
            name = f'{uuid.uuid4().hex[:12]}.{extension_for(content_type)}'
            data = ContentFile(decoded, name=name)
            data.content_type = content_type
        return super().to_internal_value(data)


def _declared_content_type(uploaded):
    """What the upload says it is: its own header first, its name second."""
    return (
        normalize_content_type(getattr(uploaded, 'content_type', None))
        or content_type_for_name(getattr(uploaded, 'name', None))
    )


class MediaAssetSerializer(serializers.ModelSerializer):
    """Reference media payload.

    `tower` / `zone` / `captured_by` are set by the viewset and never by
    the client — the subject is the URL, and the capturer is whoever is
    signed in. `byte_size` is measured from the stored file rather than
    taken on trust, because it is the number the size cap is enforced
    against.
    """

    file = Base64MediaField(use_url=True)
    captured_by_username = serializers.CharField(
        source='captured_by.username', read_only=True, default=None,
    )

    class Meta:
        model = MediaAsset
        fields = (
            'id', 'tower', 'zone', 'kind', 'file', 'caption',
            'duration_seconds', 'byte_size',
            'captured_by', 'captured_by_username', 'captured_at',
        )
        read_only_fields = (
            'tower', 'zone', 'byte_size', 'captured_by', 'captured_at',
        )

    def validate(self, attrs):
        uploaded = attrs.get('file')
        if uploaded is None:
            return attrs

        content_type = _declared_content_type(uploaded)
        # An omitted kind is inferred rather than defaulted: a client
        # that sends an audio note without saying so should get an audio
        # note, not a row claiming to be a photo that no gallery can
        # render. A kind that *is* declared must match, because a
        # mismatch means something upstream is confused and guessing
        # which half to believe would hide it.
        kind = attrs.get('kind') or kind_for_content_type(content_type)
        if kind is None:
            raise serializers.ValidationError({
                'file': (
                    f'{content_type or "This file"} is not a supported '
                    'media type.'
                ),
            })
        attrs['kind'] = kind

        try:
            check_kind(kind, content_type)
            check_size(kind, uploaded.size)
        except MediaRejected as exc:
            raise serializers.ValidationError({'file': str(exc)})
        try:
            check_duration(kind, attrs.get('duration_seconds'))
        except MediaRejected as exc:
            raise serializers.ValidationError({'duration_seconds': str(exc)})

        attrs['byte_size'] = uploaded.size
        return attrs


class MediaSubjectMixin:
    """`{id}/media/` endpoints for a viewset whose objects carry media.

    Expects `_require_geometry_author` from `CollectionAuthorGateMixin`:
    attaching media to a place is authoring it, and is gated exactly as
    moving or renaming it would be.
    """

    #: Which `MediaAsset` field points back at this viewset's model.
    media_subject_field = None

    def _media_queryset(self, subject):
        return MediaAsset.objects.filter(
            **{self.media_subject_field: subject},
        ).select_related('captured_by')

    @action(detail=True, methods=['get', 'post'])
    def media(self, request, pk=None):
        """GET lists what is attached; POST attaches (multipart or base64)."""
        subject = self.get_object()
        if request.method == 'POST':
            self._require_geometry_author(subject)
            serializer = MediaAssetSerializer(
                data=request.data, context=self.get_serializer_context(),
            )
            serializer.is_valid(raise_exception=True)
            asset = serializer.save(
                captured_by=request.user,
                **{self.media_subject_field: subject},
            )
            return Response(
                MediaAssetSerializer(
                    asset, context=self.get_serializer_context(),
                ).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(
            MediaAssetSerializer(
                self._media_queryset(subject), many=True,
                context=self.get_serializer_context(),
            ).data,
        )

    @action(
        detail=True, methods=['delete'],
        url_path=r'media/(?P<media_id>[0-9]+)',
    )
    def delete_media(self, request, pk=None, media_id=None):
        subject = self.get_object()
        self._require_geometry_author(subject)
        asset = get_object_or_404(self._media_queryset(subject), pk=media_id)
        asset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
