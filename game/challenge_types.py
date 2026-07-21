"""Pluggable challenge-type handler registry (challenge-type-system).

Every `game.Challenge` carries a `type`; the handler registered for that
type declares the submission payload it requires and how a submission is
reviewed:

- `AUTO`   -> the system resolves the outcome at submission time by
  matching the scanned code against the expected code (`NFC_QR`, `RFID`).
- `MANUAL` -> the submission is created `PENDING` and enters the staff
  review surface unchanged (`TEXT`, `PHOTO`).

The submission pipeline resolves `get_handler(challenge.type)` and
delegates — adding a challenge type means registering a handler here,
not editing the pipeline. A challenge may override its type's default
review flow through `Challenge.review_mode` (resolved by
`Challenge.effective_review_mode()`), e.g. forcing a suspicious NFC_QR
challenge to manual review without changing its type.

This module keeps no module-level model imports so `game.models` can
import the type/choice constants without a cycle.
"""

# Challenge type discriminators (Challenge.type).
TYPE_TEXT = 'TEXT'
TYPE_PHOTO = 'PHOTO'
TYPE_NFC_QR = 'NFC_QR'
TYPE_RFID = 'RFID'
CHALLENGE_TYPE_CHOICES = [
    (TYPE_TEXT, 'Text question (staff-reviewed)'),
    (TYPE_PHOTO, 'Photo evidence (staff-reviewed)'),
    (TYPE_NFC_QR, 'NFC/QR venue code (auto-validated)'),
    (TYPE_RFID, 'RFID tag scan (auto-validated)'),
]
# Types whose submissions carry a scanned code.
SCAN_TYPES = (TYPE_NFC_QR, TYPE_RFID)

# Review flows.
REVIEW_AUTO = 'AUTO'
REVIEW_MANUAL = 'MANUAL'
REVIEW_MODE_CHOICES = [
    (REVIEW_AUTO, 'Auto (validated by the system)'),
    (REVIEW_MANUAL, 'Manual (validated by staff)'),
]


class ChallengeTypeHandler:
    """Strategy for one challenge type.

    Subclasses set `type_value`, `review_mode` (the type's default flow)
    and `required_payload` (the submission payload keys the type needs),
    and implement `validate()` to resolve an outcome for AUTO flows.
    """

    type_value = None
    review_mode = REVIEW_MANUAL
    #: Payload keys a submission must supply: 'photo', 'submitted_code'.
    required_payload = ()

    def payload_error(self, submitted_code=None, photo=None):
        """Return an error message when the required payload is missing, else None."""
        if 'submitted_code' in self.required_payload and not submitted_code:
            return 'Acest tip de provocare cere un cod scanat.'
        if 'photo' in self.required_payload and not photo:
            return 'Acest tip de provocare cere o fotografie.'
        return None

    def expected_code(self, challenge, tower):
        """The code a scan submission must match (None for non-scan types)."""
        return None

    def validate(self, challenge, tower, team, submitted_code=None, photo=None):
        """Resolve the submission outcome for this type.

        MANUAL types stay PENDING — staff resolve them through the
        existing review surface.
        """
        from game.models import TeamTowerChallenge
        return TeamTowerChallenge.PENDING


class AutoValidatedHandler(ChallengeTypeHandler):
    """Shared auto-validation path: match the scanned code, else reject.

    A matching code CONFIRMS immediately (the pipeline has already
    enforced the proximity check for every type); a mismatch — or a
    consumed single-use code — REJECTS immediately and feeds the
    per-tower rejection cooldown.
    """

    review_mode = REVIEW_AUTO
    required_payload = ('submitted_code',)

    def validate(self, challenge, tower, team, submitted_code=None, photo=None):
        from game.models import TeamTowerChallenge
        expected = self.expected_code(challenge, tower)
        if expected and submitted_code == expected and not self.is_consumed(challenge, team):
            return TeamTowerChallenge.CONFIRMED
        return TeamTowerChallenge.REJECTED

    def is_consumed(self, challenge, team):
        return False


registry = {}


def register(handler_cls):
    """Class decorator: register a handler instance under its type value."""
    registry[handler_cls.type_value] = handler_cls()
    return handler_cls


def get_handler(type_value):
    """Return the handler registered for `type_value`, or None.

    Callers MUST treat None as "reject the submission safely" — an
    unknown type never captures a tower.
    """
    return registry.get(type_value)


@register
class TextChallengeHandler(ChallengeTypeHandler):
    """Location-based text question — the pre-change behavior, verbatim.

    No type-specific payload (a photo stays optional), staff-reviewed.
    """

    type_value = TYPE_TEXT
    review_mode = REVIEW_MANUAL
    required_payload = ()


@register
class PhotoChallengeHandler(ChallengeTypeHandler):
    """Photo evidence reviewed by staff. A submission must carry a photo."""

    type_value = TYPE_PHOTO
    review_mode = REVIEW_MANUAL
    required_payload = ('photo',)


@register
class NfcQrChallengeHandler(AutoValidatedHandler):
    """Partner-venue validation: match the code the venue hands out.

    Expected code is the challenge's `validation_code`. `type_config`
    may set `single_use: true`, consuming the code on the first
    successful confirmation (any later submission re-using it is
    rejected); the default (false) lets every team validate with the
    same code.
    """

    type_value = TYPE_NFC_QR

    def expected_code(self, challenge, tower):
        return challenge.validation_code if challenge else None

    def is_consumed(self, challenge, team):
        from game.models import TeamTowerChallenge
        if not (challenge and (challenge.type_config or {}).get('single_use')):
            return False
        return TeamTowerChallenge.objects.filter(
            challenge=challenge, outcome=TeamTowerChallenge.CONFIRMED,
        ).exists()


@register
class RfidChallengeHandler(AutoValidatedHandler):
    """The formalized RFID tag capture.

    Expected code derives from `tower.rfid_code`, so the tower-category
    representation and the challenge-type representation can never
    drift. Works with or without a `Challenge` row — the public
    `/tower/rfid/<code>/` capture keeps needing none.
    """

    type_value = TYPE_RFID

    def expected_code(self, challenge, tower):
        return tower.rfid_code if tower else None
