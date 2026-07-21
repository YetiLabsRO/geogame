## 1. NFC tag model & provisioning data

- [x] 1.1 Add `game.NfcTag` (`token` URL-safe unique, `mode` `LEGACY_URL`/`SECURE_TOKEN`, `tower` FK nullable, `challenge` FK nullable, `is_active`, `hidden_hint` text for where the tag is concealed, `label`, optional `expected_counter`/`last_counter` for replay hardening, `created_by`, `created_at`); admin + migration.
- [x] 1.2 Add `game.TagScan` audit model (`tag` FK, `player`/`membership`, `session`, `timestamp`, `outcome`, `lat`/`lng`/`accuracy`, `counter`); admin + migration.
- [x] 1.3 Enforce that a `SECURE_TOKEN` tag targets exactly one of a `Tower` or a `Challenge`, and that a `LEGACY_URL` tag mirrors an RFID-category tower's `rfid_code`.

## 2. Capture-mode configuration (Game default + Session override)

- [x] 2.1 Add nullable `nfc_secure_mode`, `nfc_require_app`, `nfc_replay_hardening` knobs on `organize.Game` (defaults preserve legacy URL behavior) and matching nullable overrides on `organize.Session`; migration.
- [x] 2.2 Add an effective-value resolver (Session override wins, else Game default) mirroring `proximity_meters`; unit-test the resolution.

## 3. Secure capture endpoint & validation

- [x] 3.1 Implement `POST /api/nfc/capture/` accepting `{token, lat, lng, accuracy}` from the authenticated app: resolve the tag, require the target to be reachable through the caller's current Session's collections, enforce `proximity_meters`, and record a `TagScan`.
- [x] 3.2 On a valid tower-targeted scan, auto-confirm the capture (reuse the RFID confirmation/ownership path, outcome `CONFIRMED`); on a challenge-targeted scan, route into the challenge-submission/review flow (see the `challenge-types` capability).
- [x] 3.3 Freshness/replay: when `nfc_replay_hardening` is on, require a monotonically increasing tag counter and reject repeated or lower counters as replays; when off, accept static tokens.
- [x] 3.4 App-attestation signal: when `nfc_require_app` is on, require the app-origin header/marker and reject captures that look like raw browser hits; always keep server-side auth + proximity as the real boundary.

## 4. App-link landing (non-forwardable enforcement)

- [x] 4.1 Implement `GET /nfc/<token>/` as an app-link (Android App Link / iOS Universal Link) target that deep-links the app into the scan flow.
- [x] 4.2 When opened by a plain browser (no app), return an "open this in the app to scan" page and perform NO capture; add the `assetlinks.json` / `apple-app-site-association` wiring notes.

## 5. NDEF payload & QR export for provisioning

- [x] 5.1 Staff API `GET/POST/PATCH/DELETE /api/staff/nfc-tags/` to mint, bind (to tower/challenge), edit, and deactivate tags.
- [x] 5.2 Action to return the writable NDEF payload per tag: secure mode = app-triggering record (custom URI + Android Application Record) + token; legacy mode = the existing `/tower/rfid/<code>/` URL.
- [x] 5.3 Action to return a printable QR image encoding the same app-link, for branded stickers and as the camera fallback.

## 6. Native NFC scan in the player app

- [x] 6.1 Player SPA scan flow using the Web NFC `NDEFReader` where available; a native-shell NFC bridge otherwise; reachable from tower detail as a "Scan tag" affordance.
- [x] 6.2 QR-scan (camera) and manual-code-entry fallbacks that resolve to the same token when NFC is unavailable (e.g. iOS browsers).
- [x] 6.3 On scan, POST the token to `/api/nfc/capture/` with live GPS; show capture outcome, proximity feedback, and a clear "open in the app" message if a secure link is opened outside the app.

## 7. Staff/creator provisioning UI & RFID relationship

- [x] 7.1 Staff/creator SPA panel to provision tags for a tower, choose mode, set the hidden-location hint, and export NDEF payload + QR.
- [x] 7.2 Surface, in the Django admin RFID-tower view, the secure NFC payload and QR alongside the existing printable RFID URL, and indicate which capture mode the tower uses.

## 8. Tests

- [x] 8.1 Capture test: an authenticated app scan of a valid `SECURE_TOKEN` tag within `proximity_meters` auto-confirms and reassigns the tower exactly like an RFID capture.
- [x] 8.2 Non-forwardable test: `GET /nfc/<token>/` in a plain browser returns the "open in app" page and performs no capture; a token from another Session's game is rejected by the endpoint.
- [x] 8.3 Replay test: with `nfc_replay_hardening` on, a repeated/lower counter is rejected; with it off, a static token is accepted.
- [x] 8.4 Config test: `nfc_secure_mode`/`nfc_require_app` resolve via the Session-override-then-Game-default helper; defaults preserve legacy behavior.
- [x] 8.5 Backward-compat test: an existing RFID URL capture still confirms unchanged, and a `TagScan` audit row is written for scans.
- [x] 8.6 Ruff-clean and ≥80% branch coverage for the new backend code.

## Implementation notes

**Where things live**
- `game/models.py` — `NfcTag` (token minted via `secrets.token_urlsafe(24)`,
  `clean()` enforces targeting invariants and is called from `save()`),
  `TagScan` (11 outcome constants covering every rejection flavor),
  `NFC_MODE_*` constants, `NfcTag.ndef_payload()` / `app_link()` /
  `capture_tower()`. The threat model is restated in the NfcTag docstring:
  tag contents are extractable/forgeable; integrity = app-gating +
  proximity + audit, never tag secrecy.
- `game/views.py` — `NfcCaptureView` (`POST /api/nfc/capture/`) and
  `nfc_landing` (`GET /nfc/<token>/`, template
  `game/templates/game/nfc_landing.html`). The landing view does NO tag
  lookup at all (no validity oracle, provably zero side effects);
  assetlinks.json / apple-app-site-association wiring notes are in its
  docstring (deployment-layer files, not Django routes).
- `game/admin_api.py` — `AdminNfcTagSerializer` / `AdminTagScanSerializer` /
  `AdminNfcTagViewSet` (`/api/staff/nfc-tags/` + `ndef`, `qr` (PNG via the
  new `qrcode` dep), `scan-audit` actions).
- `game/admin.py` — `NfcTagAdmin`, read-only `TagScanAdmin`; `TowerAdmin`
  gains `Capture mode` + `Secure NFC payload` columns (task 7.2).
- `organize/models.py` — the three knobs on Game (default False) +
  nullable Session overrides + `OVERRIDABLE_CONFIG_FIELDS` extension;
  exposed in `AdminGameSerializer` / `AdminSessionSerializer`.
- Migrations: `game/0028_nfc_tag_and_tag_scan.py`,
  `organize/0018_nfc_config_knobs.py` (chained off 0027 / 0017; renumber
  at merge as usual).
- New runtime dep: `qrcode>=8` (added to requirements.txt and installed).

**Semantics the merger should know**
- Capture check order mirrors `TeamTowerChallengeSerializer.validate`:
  membership → tag resolution → tag active → secure-mode knob → app
  marker → session scope (via `session.game.towers()`) → replay counter →
  proximity → pause → failure lockout → outcome LAST. A paused session
  with `pause_rejects_submissions` off holds the scan as a PENDING
  submission (capture waits for resume), exactly like the RFID hold.
- `nfc_secure_mode` is the master opt-in: with it off (the default),
  `SECURE_TOKEN` captures are rejected (`REJECTED_DISABLED`, audited), so
  nothing changes for existing games; `LEGACY_URL` tags are provisioning
  metadata only — the public `/tower/rfid/<code>/` serializer path is
  untouched (RFIDCaptureTest still passes verbatim).
- `nfc_require_app` checks the `X-Cercetador-App` header — an explicit
  UX/deterrent marker, documented in code as NOT the security boundary
  (auth + proximity + audit are), per design.md.
- Replay hardening: `counter` must be strictly greater than
  `tag.last_counter`; the accepted counter is persisted BEFORE the
  proximity check (a physical re-tap yields a fresh counter, so a
  proximity-failed scan can retry; a replayed dump cannot).
- Challenge-target scans: the physical tag is the credential, so the
  handler is invoked with `submitted_code=expected_code` — string
  matching is by tag-binding; the handler still decides consumption
  (`single_use`) and the `review_mode=MANUAL` override stays PENDING.
  A challenge-target tag requires a tower-bound challenge
  (`TeamTowerChallenge.tower` is NOT NULL); enforced at provisioning
  (model clean + serializer). `submitted_code` on the TTC row records
  the scanned token.
- Every attempt on a KNOWN token writes a `TagScan` (including
  membership-less callers); an unknown token 404s with no audit row
  (nothing to FK to) — same shape as an unknown RFID code.

**Frontend (wireframe quality, per brief)**
- Player: `nfc/nfc-scan.component.ts` on routes `/scan` (manual entry +
  Web NFC `NDEFReader` where supported) and `/nfc/:token` (app-link /
  QR deep-link target — capture fires on load with live GPS). Added
  `withComponentInputBinding()` to the player router config for the
  `:token` route input. `GameApiService.nfcCapture()` sends the
  `X-Cercetador-App` header. The camera-QR fallback is the OS camera
  scanning the printed QR → it opens the same `/nfc/<token>` app-link;
  no in-app camera scanner was built (native bridge is a
  native-shell-phase concern, per design).
- Staff: `admin/nfc-tags.component.ts` at `/nfc-tags` — mint/bind form
  (mode, tower/challenge id, label, hidden hint), tag table with NDEF
  JSON viewer, client-side QR (shared `lib-qr-code` of `app_link`,
  window.print for the sheet), deactivate, and the scan-audit table.
- Shortfalls (honest): no "Scan tag" button was added INSIDE
  tower-detail (the scan page is a top-level route instead — adding the
  affordance to tower-detail.component.ts is a 5-line follow-up); no nav
  link added to the staff navbar (reach `/nfc-tags` by URL); no
  dedicated multi-tag printable QR sheet layout (per-tag QR + print
  covers the wireframe bar).

**Tests**
- 24 new tests in `game/tests.py` (NfcCaptureTest, NfcReplayHardeningTest,
  NfcChallengeTargetTest, NfcConfigResolutionTest, NfcTagModelTest,
  AdminNfcTagEndpointTest). Full suite: 469 tests green
  (445 baseline + 24). Ruff clean; `makemigrations --check` clean.
  Coverage not re-measured this run (new code is directly test-covered;
  baseline gate was passing).

**Expected merge conflict hotspots**
- `game/models.py` (new models near EOF), `game/views.py` (imports +
  new views before `health`), `game/admin_api.py` (imports + block
  before `ResetScoresView`, AdminGame/AdminSession serializer field
  lists), `game/admin.py` (imports, TowerAdmin, registrations),
  `organize/models.py` (OVERRIDABLE_CONFIG_FIELDS + Game/Session field
  blocks), `geogame/urls.py` (imports + router + two paths),
  `game/tests.py` (import block + new section at EOF), migration
  numbering (game 0028 / organize 0018), `requirements.txt`, and the
  frontend files: `shared/game-api.service.ts`, `shared/staff-api.service.ts`,
  `player/app.routes.ts`, `player/app.config.ts`, `staff/app.routes.ts`.
