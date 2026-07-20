## Why

Today a `game.Challenge` is text-only: it carries `text` + `difficulty`, is bound to a tower or generic, and is always judged the same way — a human reads the attempt and confirms or rejects it. But the product goal is for a challenge to be **anything**: answer a question, prove you were somewhere with a photo, or complete a real-world transaction at a partner venue and scan a code the venue hands you. This is a key commercial hook (a tower hosted at a bar: buy the drink, scan the QR the bartender gives you, capture the tower). The existing RFID tower capture is already a second, code-scan-based way to capture a tower, but it lives outside the challenge model as a tower `category`. This change generalizes `Challenge` into a **pluggable type system** so each challenge declares its own validation payload and review flow (automatic vs manual), and folds RFID capture in as one of those types — without changing the difficulty roster, the generic fallback pool, or existing text challenges.

## What Changes

- Add a `Challenge.type` discriminator with four types: `TEXT` (location-based text question, the current behavior), `PHOTO` (photo evidence submitted for validation), `NFC_QR` (venue/partner validation — scan a QR/NFC code handed out at the venue), and `RFID` (the existing tag-scanned tower capture, now formalized as a challenge type).
- Each type carries its own **validation** (what payload a submission must include and how it is checked) and **review flow**: `NFC_QR`/`RFID` are auto-validated (a matching scanned code + proximity auto-confirms), `TEXT`/`PHOTO` are manually reviewed by staff — exactly as text challenges are reviewed today.
- Introduce a pluggable **challenge-type handler registry** (a strategy per type) so "a challenge can be anything" is extensible: adding a new type is registering a handler, not rewriting the submission pipeline.
- Add type-specific config: `Challenge.validation_code` (the code embedded in the QR/NFC handed out at a venue) and a `Challenge.type_config` JSON for per-type extras (partner/venue label, single-use flag); add `TeamTowerChallenge.submitted_code` to carry the scanned code on scan-type submissions.
- Preserve the difficulty-bucketed next-challenge roster and the game-wide generic fallback pool (from the `challenges` capability), the tower-specific-vs-generic distinction, the per-tower rejection cooldown, and the proximity check — all now type-agnostic.
- Backward compatible: `Challenge.type` defaults to `TEXT`; a data migration stamps every existing challenge as `TEXT` so behavior is byte-for-byte identical.

## Capabilities

### New Capabilities
- `challenge-types`: a pluggable taxonomy of challenge types (`TEXT`, `PHOTO`, `NFC_QR`, `RFID`), each with its own validation payload and auto-vs-manual review flow, resolved through a handler registry.

### Modified Capabilities
- `challenges`: `Challenge` gains a `type` discriminator and type-specific config; the difficulty roster, generic fallback, and tower-specific-vs-generic behavior are preserved and made type-agnostic.
- `challenge-submission`: submission validation and the confirm/reject flow dispatch by challenge type — auto-confirm for scan types, staff review for text/photo types — reusing the existing proximity check, cooldown, and auto-capture-on-confirm.
- `rfid-capture`: RFID tower capture is formalized as the `RFID` challenge type and shares the auto-validated review path with `NFC_QR`; the public scan route and printable admin URL are preserved.

## Impact

- **Models**: add `Challenge.type` (enum, default `TEXT`), `Challenge.validation_code` (nullable), `Challenge.type_config` (JSON), optional `Challenge.review_mode` override; add `TeamTowerChallenge.submitted_code` (nullable). New non-model `ChallengeTypeHandler` registry in the `game` app.
- **APIs**: `GET /api/challenges/` returns each challenge's `type` and the submission payload it expects; `POST /api/team_tower_challenges/` accepts a `submitted_code` and dispatches validation/review by type; a validation endpoint/action for scan submissions.
- **Frontend**: player app renders a per-type submission UI (text question, photo capture, QR/NFC scan); staff/creator authoring UI gains a challenge-type picker and per-type config fields.
- **Migrations/other**: data migration stamping all existing challenges `type=TEXT`; RFID-category towers keep working through the `RFID` handler. Every new field defaults to preserve current behavior.
