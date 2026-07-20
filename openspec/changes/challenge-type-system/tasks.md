## 1. Challenge model & type discriminator

- [ ] 1.1 Add `Challenge.type` (string enum `TEXT`/`PHOTO`/`NFC_QR`/`RFID`, default `TEXT`), `Challenge.validation_code` (nullable, for scan types), `Challenge.type_config` (JSONField, default empty dict), and nullable `Challenge.review_mode` override; makemigrations.
- [ ] 1.2 Add `TeamTowerChallenge.submitted_code` (nullable CharField) to carry the scanned code on scan-type submissions.
- [ ] 1.3 Data migration: stamp every existing `Challenge` with `type=TEXT` (explicit, idempotent).
- [ ] 1.4 Django admin: challenge-type picker; show `validation_code`/`type_config` only for the relevant types; keep the existing text/difficulty/tower fields.

## 2. Challenge-type handler registry (pluggable validation)

- [ ] 2.1 Add a `ChallengeTypeHandler` base class exposing `review_mode` (`AUTO`/`MANUAL`), `required_payload`, and `validate(submission) -> outcome`, plus a `registry` keyed by type value.
- [ ] 2.2 Implement `TextChallengeHandler` (MANUAL, no scan payload) reproducing today's staff-reviewed flow.
- [ ] 2.3 Implement `PhotoChallengeHandler` (MANUAL, requires a photo).
- [ ] 2.4 Implement `NfcQrChallengeHandler` (AUTO, requires `submitted_code`; confirm iff code == `validation_code` and proximity holds; honor `single_use`).
- [ ] 2.5 Implement `RfidChallengeHandler` (AUTO, requires `submitted_code`; expected code derived from `tower.rfid_code`; confirm iff match and proximity holds).
- [ ] 2.6 Resolve the effective review mode as `challenge.review_mode or handler.review_mode`.

## 3. Submission pipeline dispatch (auto vs manual)

- [ ] 3.1 In the `POST /api/team_tower_challenges/` viewset, resolve `handler = registry[challenge.type]`, validate the type-specific payload, and keep the existing proximity check and per-tower rejection cooldown for all types.
- [ ] 3.2 For AUTO types: on a matching scan set outcome `CONFIRMED` and run `tower.assign_to_team(team)` inline; on a mismatch set `REJECTED` (feeding the cooldown); record `submitted_code`.
- [ ] 3.3 For MANUAL types: create the submission as `PENDING` and route it to the existing staff review surface unchanged.
- [ ] 3.4 Ensure `checked_by`/`verified_at` are set appropriately for auto outcomes (system-attributed) vs manual outcomes (staff-attributed).

## 4. NFC/QR venue type & single-use codes

- [ ] 4.1 Support `type_config` keys: partner/venue label and `single_use` (default false).
- [ ] 4.2 When `single_use` is true, consume a `validation_code` on first successful confirm and reject re-use; when false, allow every team to validate with the same code.
- [ ] 4.3 Surface the printable/handout representation of an NFC_QR challenge's `validation_code` to staff (analogous to the RFID printable URL).

## 5. RFID type formalization

- [ ] 5.1 Route `/tower/rfid/<rfid_code>/` through `RfidChallengeHandler` so it builds an `RFID`-type auto submission using `tower.rfid_code` as the expected code, preserving the existing outcome and proximity behavior.
- [ ] 5.2 Keep `Tower.category == RFID` as the trigger and the printable admin URL; assert the two representations stay consistent.

## 6. API & serializers

- [ ] 6.1 Extend the challenge serializer to emit `type`, the effective review mode, and the submission payload the client must supply (without leaking `validation_code` to players).
- [ ] 6.2 Extend the submission serializer/endpoint to accept `submitted_code` and return the resolved outcome (immediate for AUTO, `PENDING` for MANUAL).
- [ ] 6.3 Keep `GET /api/challenges/` returning both tower-specific and generic challenges of every type for the current Session's Game.

## 7. Frontend (player + staff)

- [ ] 7.1 Player app: render a per-type submission UI — text question, photo capture, and QR/NFC code scan (accept a pasted/scanned code as a string for now) — chosen from the challenge's `type`.
- [ ] 7.2 Staff/creator authoring: challenge-type picker with per-type config fields (validation code, venue label, single-use, review-mode override).
- [ ] 7.3 Staff review surface: unchanged for MANUAL types; show AUTO outcomes as read-only audit rows.

## 8. Tests

- [ ] 8.1 Roster regression: an all-`TEXT` game returns the identical next-challenge sequence and staff-review behavior as before the change.
- [ ] 8.2 NFC_QR: matching code + in-range → auto `CONFIRMED` + capture; wrong code → `REJECTED` + cooldown; out-of-range → rejected; `single_use` consumed on first use.
- [ ] 8.3 PHOTO: submission without a photo is rejected; with a photo is `PENDING` and reaches staff review; confirm captures the tower.
- [ ] 8.4 RFID parity: the `/tower/rfid/<code>/` route and a manually built `RFID` submission reach the same auto-confirm outcome; proximity still enforced.
- [ ] 8.5 `review_mode` override: an `NFC_QR` challenge forced to `MANUAL` stays `PENDING` on a matching scan.
- [ ] 8.6 Registry: an unknown/unregistered type is rejected safely; migration stamps legacy rows `TEXT`. Coverage ≥80%, ruff-clean.
