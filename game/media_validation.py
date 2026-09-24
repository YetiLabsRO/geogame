"""Upload validation for challenge media (challenge-media capability).

Validate and reject; never transcode. A file outside its kind's MIME
allowlist, byte ceiling, or duration ceiling is refused at upload with a
message naming the limit AND the actual value, so a creator learns the
bound at the moment they hit it rather than at play time.

Duration is probed with mutagen, which is pure Python and needs no
system binary. The MIME allowlists in settings are kept to formats
mutagen can read, so `_probe_duration` returning None means the file is
genuinely unreadable rather than merely unsupported — and an audio or
video file whose duration cannot be determined is rejected rather than
stored with an unknown length.
"""
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import ChallengeMedia


def _human_bytes(value):
    """Render a byte count the way an error message should read."""
    megabytes = value / (1024 * 1024)
    if megabytes >= 1:
        return f'{megabytes:.1f}MB'
    return f'{value / 1024:.0f}KB'


def _probe_duration(uploaded_file):
    """Seconds of audio/video in `uploaded_file`, or None if unreadable."""
    import mutagen

    position = uploaded_file.tell()
    try:
        uploaded_file.seek(0)
        probed = mutagen.File(uploaded_file)
    except Exception:  # noqa: BLE001 - any parse failure means "unreadable"
        return None
    finally:
        uploaded_file.seek(position)
    length = getattr(getattr(probed, 'info', None), 'length', None)
    if length is None or length <= 0:
        return None
    return float(length)


def validate_upload(kind, uploaded_file, content_type=None):
    """Check one upload against its kind's limits.

    Returns `(size_in_bytes, duration_or_None)` on success and raises
    `ValidationError` naming the breached limit otherwise.
    """
    valid_kinds = dict(ChallengeMedia.KIND_CHOICES)
    if kind not in valid_kinds:
        raise ValidationError(
            f'Unknown media kind {kind!r}. Expected one of: '
            f'{", ".join(sorted(valid_kinds))}.',
        )

    allowed_types = settings.CHALLENGE_MEDIA_MIME_TYPES[kind]
    declared = content_type or getattr(uploaded_file, 'content_type', '') or ''
    if declared not in allowed_types:
        raise ValidationError(
            f'{declared or "unknown"} is not an accepted {kind.lower()} type. '
            f'Accepted: {", ".join(allowed_types)}.',
        )

    max_bytes = settings.CHALLENGE_MEDIA_MAX_BYTES[kind]
    size = uploaded_file.size
    if size > max_bytes:
        raise ValidationError(
            f'This {kind.lower()} is {_human_bytes(size)}; the limit is '
            f'{_human_bytes(max_bytes)}.',
        )

    if kind not in ChallengeMedia.TIMED_KINDS:
        return size, None

    duration = _probe_duration(uploaded_file)
    if duration is None:
        raise ValidationError(
            f'Could not read the duration of this {kind.lower()}. The file '
            'may be corrupt or in an unsupported container.',
        )
    max_seconds = settings.CHALLENGE_MEDIA_MAX_SECONDS[kind]
    if duration > max_seconds:
        raise ValidationError(
            f'This {kind.lower()} is {duration:.0f}s long; the limit is '
            f'{max_seconds}s.',
        )
    return size, duration
