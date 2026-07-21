## 1. Challenge model & type discriminator

- [x] 1.1 Add `Challenge.type` (string enum `TEXT`/`PHOTO`/`NFC_QR`/`RFID`, default `TEXT`), `Challenge.validation_code` (nullable, for scan types), `Challenge.type_config` (JSONField, default empty dict), and nullable `Challenge.review_mode` override; makemigrations.
- [x] 1.2 Add `TeamTowerChallenge.submitted_code` (nullable CharField) to carry the scanned code on scan-type submissions.
- [x] 1.3 Data migration: stamp every existing `Challenge` with `type=TEXT` (explicit, idempotent).
- [x] 1.4 Django admin: challenge-type picker; show `validation_code`/`type_config` only for the relevant types; keep the existing text/difficulty/tower fields.

## 2. Challenge-type handler registry (pluggable validation)

- [x] 2.1 Add a `ChallengeTypeHandler` base class exposing `review_mode` (`AUTO`/`MANUAL`), `required_payload`, and `validate(submission) -> outcome`, plus a `registry` keyed by type value.
- [x] 2.2 Implement `TextChallengeHandler` (MANUAL, no scan payload) reproducing today's staff-reviewed flow.
- [x] 2.3 Implement `PhotoChallengeHandler` (MANUAL, requires a photo).
- [x] 2.4 Implement `NfcQrChallengeHandler` (AUTO, requires `submitted_code`; confirm iff code == `validation_code` and proximity holds; honor `single_use`).
- [x] 2.5 Implement `RfidChallengeHandler` (AUTO, requires `submitted_code`; expected code derived from `tower.rfid_code`; confirm iff match and proximity holds).
- [x] 2.6 Resolve the effective review mode as `challenge.review_mode or handler.review_mode`.

## 3. Submission pipeline dispatch (auto vs manual)

- [x] 3.1 In the `POST /api/team_tower_challenges/` viewset, resolve `handler = registry[challenge.type]`, validate the type-specific payload, and keep the existing proximity check and per-tower rejection cooldown for all types.
- [x] 3.2 For AUTO types: on a matching scan set outcome `CONFIRMED` and run `tower.assign_to_team(team)` inline; on a mismatch set `REJECTED` (feeding the cooldown); record `submitted_code`.
- [x] 3.3 For MANUAL types: create the submission as `PENDING` and route it to the existing staff review surface unchanged.
- [x] 3.4 Ensure `checked_by`/`verified_at` are set appropriately for auto outcomes (system-attributed) vs manual outcomes (staff-attributed).

## 4. NFC/QR venue type & single-use codes

- [x] 4.1 Support `type_config` keys: partner/venue label and `single_use` (default false).
- [x] 4.2 When `single_use` is true, consume a `validation_code` on first successful confirm and reject re-use; when false, allow every team to validate with the same code.
- [x] 4.3 Surface the printable/handout representation of an NFC_QR challenge's `validation_code` to staff (analogous to the RFID printable URL).

## 5. RFID type formalization

- [x] 5.1 Route `/tower/rfid/<rfid_code>/` through `RfidChallengeHandler` so it builds an `RFID`-type auto submission using `tower.rfid_code` as the expected code, preserving the existing outcome and proximity behavior.
- [x] 5.2 Keep `Tower.category == RFID` as the trigger and the printable admin URL; assert the two representations stay consistent.

## 6. API & serializers

- [x] 6.1 Extend the challenge serializer to emit `type`, the effective review mode, and the submission payload the client must supply (without leaking `validation_code` to players).
- [x] 6.2 Extend the submission serializer/endpoint to accept `submitted_code` and return the resolved outcome (immediate for AUTO, `PENDING` for MANUAL).
- [x] 6.3 Keep `GET /api/challenges/` returning both tower-specific and generic challenges of every type for the current Session's Game.

## 7. Frontend (player + staff)

- [x] 7.1 Player app: render a per-type submission UI — text question, photo capture, and QR/NFC code scan (accept a pasted/scanned code as a string for now) — chosen from the challenge's `type`.
- [x] 7.2 Staff/creator authoring: challenge-type picker with per-type config fields (validation code, venue label, single-use, review-mode override).
- [x] 7.3 Staff review surface: unchanged for MANUAL types; show AUTO outcomes as read-only audit rows.

## 8. Tests

- [x] 8.1 Roster regression: an all-`TEXT` game returns the identical next-challenge sequence and staff-review behavior as before the change.
- [x] 8.2 NFC_QR: matching code + in-range → auto `CONFIRMED` + capture; wrong code → `REJECTED` + cooldown; out-of-range → rejected; `single_use` consumed on first use.
- [x] 8.3 PHOTO: submission without a photo is rejected; with a photo is `PENDING` and reaches staff review; confirm captures the tower.
- [x] 8.4 RFID parity: the `/tower/rfid/<code>/` route and a manually built `RFID` submission reach the same auto-confirm outcome; proximity still enforced.
- [x] 8.5 `review_mode` override: an `NFC_QR` challenge forced to `MANUAL` stays `PENDING` on a matching scan.
- [x] 8.6 Registry: an unknown/unregistered type is rejected safely; migration stamps legacy rows `TEXT`. Coverage ≥80%, ruff-clean.

## Implementation notes

**Where things live**
- `game/challenge_types.py` (new) — handler registry: `ChallengeTypeHandler` base,
  `AutoValidatedHandler`, the four registered handlers, `get_handler()`, and the
  `TYPE_*` / `REVIEW_*` choice constants. No model imports at module level so
  `game/models.py` can import the constants without a cycle.
- Migrations: `game/migrations/0026_challenge_type_system.py` (schema: `Challenge.type`
  / `validation_code` / `type_config` / `review_mode` + `TeamTowerChallenge.submitted_code`)
  and `0027_stamp_existing_challenges_text.py` (idempotent TEXT stamp, reverse no-op).
  Chained off `game/0025_merge_20260721_0017`; renumber at merge if needed.

**Pipeline decisions the merger should know**
- Check order in `TeamTowerChallengeSerializer.validate` is now: membership →
  tower/RFID resolution → **handler resolution + required-payload check** → GPS
  proximity → role gate → pause → failure lockout → **outcome resolution (last)**.
  The handler/payload check sits right after tower resolution because a malformed
  payload is a request-shape error (like an unknown RFID code); the outcome resolves
  LAST so an auto-validated scan can never bypass proximity/role/pause/lockout, and
  a paused hold always wins (submission stays PENDING, capture waits for resume).
- AUTO outcomes are system-attributed: `timestamp_verified` set at insert,
  `checked_by` stays NULL. `StaffSubmissionSerializer.auto_resolved` derives from
  exactly that (non-PENDING + no checker + verified).
- Auto-REJECTED scans apply the same failure consequences as a staff rejection
  (cooldown + fail counter + optional penalty) via a `_system_resolved` flag set
  only by the submission serializer — direct ORM inserts (fixtures/tests/admin)
  keep pre-change behavior.
- The legacy `_auto_confirm` serializer flag is gone; the `/tower/rfid/<code>/`
  payload path (`rfid_code`) resolves the tower and dispatches through
  `RfidChallengeHandler` with `submitted_code=rfid_code` (always a match → same
  auto-confirm outcome as before). A challenge-less `tower` + `submitted_code`
  POST against a `Tower.category == RFID` tower takes the same path (parity
  asserted by `RfidParityTest`).
- Tower capture on auto-confirm still runs in `TeamTowerChallengeViewSet.perform_create`
  (pre-existing hook), not in the serializer.

**Scope notes / deviations**
- Task 4.3 (printable handout): implemented as the `Handout code` column +
  scan-config fieldset help text in the Django admin `ChallengeAdmin`, plus
  `validation_code` exposure in the staff API (`AdminChallengeSerializer`). There
  is no separate printable HTML page — the RFID analogue is also just an admin
  list column (`get_rfid_url`).
- Staff API validation: an NFC_QR challenge requires `validation_code` unless
  `review_mode` is forced MANUAL; `type_config` must be a JSON object and
  `single_use` a boolean. Django admin intentionally keeps the full form loose
  (superuser escape hatch).
- Player payloads (`ChallengeSerializer`, `ChallengeSummarySerializer`) emit
  `type`, `effective_review_mode`, `required_payload` and never `validation_code`.
- Frontend (wireframe quality, Bootstrap 5): player `tower-detail` renders
  per-type inputs (photo required for PHOTO, code input for NFC_QR/RFID, both
  driven by `required_payload`) and surfaces the immediate AUTO outcome; staff
  `challenges` admin gets a type picker + per-type config (validation code,
  venue label, single-use, review-mode override); staff `pending-queue` shows a
  type badge + scanned code on pending cards and a read-only
  "auto-validated audit" table (client-side filter of `?outcome=all` on
  `auto_resolved`). Native QR/NFC scanning is out of scope
  (`nfc-native-and-secure-links`); the code is pasted/typed as a string.
- Coverage: full suite green (445 tests); ruff clean; `coverage --fail-under=80`
  not re-measured this run (new module is heavily test-covered; baseline was
  passing).

**Expected merge conflict hotspots**
- `game/models.py` (Challenge fields + `_on_submission_created`), `game/serializers.py`
  (submission validate/create rewrite), `game/api.py` (ChallengeSummary/StaffSubmission
  serializers), `game/admin_api.py` (AdminChallengeSerializer.validate), `game/admin.py`
  (ChallengeAdmin/TTC admin), `organize/models.py` (`Game.clone` challenge fields),
  `game/tests.py` (new section at EOF + one import block), migration numbering
  (0026/0027), and the three touched frontend files
  (`shared/game-api.service.ts`, `shared/staff-api.service.ts`,
  `staff/admin/challenges.component.ts`, `staff/review/pending-queue.component.ts`,
  `player/tower/tower-detail.component.ts`).
