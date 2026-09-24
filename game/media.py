"""Reference media — the kinds a curator may attach, and the bounds on each.

This module holds no models. `game.models` imports the kind constants
from here, so anything that needs to *validate* media can import the
rules without importing the model layer, and the rules stay in one
place rather than being re-stated in a serializer, a form and a test.

Two things are deliberately separated:

* **What a kind is** — the content types a browser actually produces for
  a camera, a `MediaRecorder` and a video capture. A file whose type
  matches no kind is refused rather than stored: an attachment nothing
  can play or display describes nothing.
* **How much of it** — per-kind size caps, plus a duration cap for the
  two kinds that have a duration. Both come from settings so an install
  with a fat pipe can raise them, and both are checked server-side,
  because a client-side cap is a courtesy and not a control.
"""
import mimetypes

from django.conf import settings

MEDIA_IMAGE = 'IMAGE'
MEDIA_AUDIO = 'AUDIO'
MEDIA_VIDEO = 'VIDEO'

MEDIA_KIND_CHOICES = [
    (MEDIA_IMAGE, 'Photo'),
    (MEDIA_AUDIO, 'Audio note'),
    (MEDIA_VIDEO, 'Video clip'),
]
MEDIA_KINDS = tuple(kind for kind, _ in MEDIA_KIND_CHOICES)

# What each kind accepts. Browsers are not consistent here: Chrome's
# MediaRecorder emits `audio/webm`, Safari `audio/mp4`; an iPhone camera
# roll hands over `image/heic`. Listing them is duller than sniffing and
# much harder to get subtly wrong.
CONTENT_TYPES_BY_KIND = {
    MEDIA_IMAGE: frozenset({
        'image/jpeg', 'image/png', 'image/webp', 'image/gif',
        'image/heic', 'image/heif',
    }),
    MEDIA_AUDIO: frozenset({
        'audio/webm', 'audio/ogg', 'audio/mpeg', 'audio/mp3', 'audio/mp4',
        'audio/aac', 'audio/x-m4a', 'audio/wav', 'audio/x-wav',
    }),
    MEDIA_VIDEO: frozenset({
        'video/webm', 'video/mp4', 'video/quicktime', 'video/ogg',
        'video/3gpp', 'video/x-matroska',
    }),
}

# Extensions we hand a decoded data URL, keyed by content type. The
# offline queue replays a capture as base64 with no filename of its own,
# and a stored file with no extension is one a web server will serve as
# `application/octet-stream`.
EXTENSION_BY_CONTENT_TYPE = {
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
    'image/gif': 'gif', 'image/heic': 'heic', 'image/heif': 'heif',
    'audio/webm': 'weba', 'audio/ogg': 'ogg', 'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3', 'audio/mp4': 'm4a', 'audio/aac': 'aac',
    'audio/x-m4a': 'm4a', 'audio/wav': 'wav', 'audio/x-wav': 'wav',
    'video/webm': 'webm', 'video/mp4': 'mp4', 'video/quicktime': 'mov',
    'video/ogg': 'ogv', 'video/3gpp': '3gp', 'video/x-matroska': 'mkv',
}

# Defaults, overridable per install through `MEDIA_ASSET_LIMITS`.
#
# The image cap is generous because the field client downscales before
# it uploads, so hitting it means something went wrong rather than
# someone being careless. The video caps are the tight ones: a clip is
# an *approach* or a *route*, thirty seconds of it, not a tour.
DEFAULT_LIMITS = {
    MEDIA_IMAGE: {'max_bytes': 12 * 1024 * 1024, 'max_seconds': None},
    MEDIA_AUDIO: {'max_bytes': 12 * 1024 * 1024, 'max_seconds': 180},
    MEDIA_VIDEO: {'max_bytes': 48 * 1024 * 1024, 'max_seconds': 30},
}


class MediaRejected(Exception):
    """An upload that may not be stored, carrying the reason verbatim.

    The message is written to be shown to the curator who is standing in
    the place they captured it, so it names the limit and what they
    actually handed over — "at most 30 s; this clip is 47 s" — rather
    than saying the upload was invalid.
    """


def limits_for(kind):
    """The size and duration caps in force for `kind`.

    An install may override either facet of either kind; whatever it
    leaves out falls back to the default, so a settings file naming one
    number does not have to restate the other five.
    """
    configured = getattr(settings, 'MEDIA_ASSET_LIMITS', None) or {}
    limits = dict(DEFAULT_LIMITS.get(kind, {}))
    limits.update(configured.get(kind, {}))
    return limits


def normalize_content_type(raw):
    """`audio/webm;codecs=opus` → `audio/webm`; anything falsy → None."""
    if not raw:
        return None
    return raw.split(';', 1)[0].strip().lower() or None


def content_type_for_name(name):
    """Best guess from a filename, for an upload that declared no type."""
    if not name:
        return None
    return normalize_content_type(mimetypes.guess_type(name)[0])


def kind_for_content_type(content_type):
    """Which kind accepts this content type, or None if none does."""
    for kind, accepted in CONTENT_TYPES_BY_KIND.items():
        if content_type in accepted:
            return kind
    return None


def extension_for(content_type):
    return EXTENSION_BY_CONTENT_TYPE.get(content_type, 'bin')


def _format_bytes(value):
    megabytes = value / (1024 * 1024)
    if megabytes >= 1:
        return f'{megabytes:.1f} MB'
    return f'{value / 1024:.0f} KB'


def check_kind(kind, content_type):
    """Refuse a file whose type does not match the kind it was sent as.

    Both directions matter. An unknown type has no kind at all and
    cannot be stored; a known type sent under the wrong kind would give
    a media strip a chip that claims to be audio and renders as an
    image, so it is refused rather than silently reclassified — the
    client knows what it captured, and a mismatch means something is
    wrong upstream of here.
    """
    if kind not in MEDIA_KINDS:
        raise MediaRejected(
            f'{kind!r} is not a kind of media this system stores.',
        )
    if content_type is None:
        raise MediaRejected(
            'The file did not say what type it is, so it cannot be stored '
            'as media.',
        )
    actual = kind_for_content_type(content_type)
    if actual is None:
        raise MediaRejected(
            f'{content_type} is not a supported media type.',
        )
    if actual != kind:
        raise MediaRejected(
            f'{content_type} is {actual.lower()}, not {kind.lower()}.',
        )


def check_size(kind, byte_size):
    max_bytes = limits_for(kind).get('max_bytes')
    if max_bytes is not None and byte_size > max_bytes:
        raise MediaRejected(
            f'{dict(MEDIA_KIND_CHOICES)[kind]} may be at most '
            f'{_format_bytes(max_bytes)}; this file is '
            f'{_format_bytes(byte_size)}.',
        )


def check_duration(kind, duration_seconds):
    if duration_seconds is None:
        return
    if duration_seconds < 0:
        raise MediaRejected('A clip cannot have a negative duration.')
    max_seconds = limits_for(kind).get('max_seconds')
    if max_seconds is not None and duration_seconds > max_seconds:
        raise MediaRejected(
            f'{dict(MEDIA_KIND_CHOICES)[kind]} may be at most '
            f'{max_seconds:g} s; this one is {duration_seconds:g} s.',
        )
