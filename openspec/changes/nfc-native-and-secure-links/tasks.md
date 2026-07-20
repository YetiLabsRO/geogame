## 1. NFC tag model & provisioning data

- [ ] 1.1 Add `game.NfcTag` (`token` URL-safe unique, `mode` `LEGACY_URL`/`SECURE_TOKEN`, `tower` FK nullable, `challenge` FK nullable, `is_active`, `hidden_hint` text for where the tag is concealed, `label`, optional `expected_counter`/`last_counter` for replay hardening, `created_by`, `created_at`); admin + migration.
- [ ] 1.2 Add `game.TagScan` audit model (`tag` FK, `player`/`membership`, `session`, `timestamp`, `outcome`, `lat`/`lng`/`accuracy`, `counter`); admin + migration.
- [ ] 1.3 Enforce that a `SECURE_TOKEN` tag targets exactly one of a `Tower` or a `Challenge`, and that a `LEGACY_URL` tag mirrors an RFID-category tower's `rfid_code`.

## 2. Capture-mode configuration (Game default + Session override)

- [ ] 2.1 Add nullable `nfc_secure_mode`, `nfc_require_app`, `nfc_replay_hardening` knobs on `organize.Game` (defaults preserve legacy URL behavior) and matching nullable overrides on `organize.Session`; migration.
- [ ] 2.2 Add an effective-value resolver (Session override wins, else Game default) mirroring `proximity_meters`; unit-test the resolution.

## 3. Secure capture endpoint & validation

- [ ] 3.1 Implement `POST /api/nfc/capture/` accepting `{token, lat, lng, accuracy}` from the authenticated app: resolve the tag, require the target to be reachable through the caller's current Session's collections, enforce `proximity_meters`, and record a `TagScan`.
- [ ] 3.2 On a valid tower-targeted scan, auto-confirm the capture (reuse the RFID confirmation/ownership path, outcome `CONFIRMED`); on a challenge-targeted scan, route into the challenge-submission/review flow (see the `challenge-types` capability).
- [ ] 3.3 Freshness/replay: when `nfc_replay_hardening` is on, require a monotonically increasing tag counter and reject repeated or lower counters as replays; when off, accept static tokens.
- [ ] 3.4 App-attestation signal: when `nfc_require_app` is on, require the app-origin header/marker and reject captures that look like raw browser hits; always keep server-side auth + proximity as the real boundary.

## 4. App-link landing (non-forwardable enforcement)

- [ ] 4.1 Implement `GET /nfc/<token>/` as an app-link (Android App Link / iOS Universal Link) target that deep-links the app into the scan flow.
- [ ] 4.2 When opened by a plain browser (no app), return an "open this in the app to scan" page and perform NO capture; add the `assetlinks.json` / `apple-app-site-association` wiring notes.

## 5. NDEF payload & QR export for provisioning

- [ ] 5.1 Staff API `GET/POST/PATCH/DELETE /api/staff/nfc-tags/` to mint, bind (to tower/challenge), edit, and deactivate tags.
- [ ] 5.2 Action to return the writable NDEF payload per tag: secure mode = app-triggering record (custom URI + Android Application Record) + token; legacy mode = the existing `/tower/rfid/<code>/` URL.
- [ ] 5.3 Action to return a printable QR image encoding the same app-link, for branded stickers and as the camera fallback.

## 6. Native NFC scan in the player app

- [ ] 6.1 Player SPA scan flow using the Web NFC `NDEFReader` where available; a native-shell NFC bridge otherwise; reachable from tower detail as a "Scan tag" affordance.
- [ ] 6.2 QR-scan (camera) and manual-code-entry fallbacks that resolve to the same token when NFC is unavailable (e.g. iOS browsers).
- [ ] 6.3 On scan, POST the token to `/api/nfc/capture/` with live GPS; show capture outcome, proximity feedback, and a clear "open in the app" message if a secure link is opened outside the app.

## 7. Staff/creator provisioning UI & RFID relationship

- [ ] 7.1 Staff/creator SPA panel to provision tags for a tower, choose mode, set the hidden-location hint, and export NDEF payload + QR.
- [ ] 7.2 Surface, in the Django admin RFID-tower view, the secure NFC payload and QR alongside the existing printable RFID URL, and indicate which capture mode the tower uses.

## 8. Tests

- [ ] 8.1 Capture test: an authenticated app scan of a valid `SECURE_TOKEN` tag within `proximity_meters` auto-confirms and reassigns the tower exactly like an RFID capture.
- [ ] 8.2 Non-forwardable test: `GET /nfc/<token>/` in a plain browser returns the "open in app" page and performs no capture; a token from another Session's game is rejected by the endpoint.
- [ ] 8.3 Replay test: with `nfc_replay_hardening` on, a repeated/lower counter is rejected; with it off, a static token is accepted.
- [ ] 8.4 Config test: `nfc_secure_mode`/`nfc_require_app` resolve via the Session-override-then-Game-default helper; defaults preserve legacy behavior.
- [ ] 8.5 Backward-compat test: an existing RFID URL capture still confirms unchanged, and a `TagScan` audit row is written for scans.
- [ ] 8.6 Ruff-clean and ≥80% branch coverage for the new backend code.
