## Why

The game wants a physical area — a city block, a park, a forest — to come alive through touch. A hidden NFC tag inside a tree trunk or behind wall plaster is close enough to scan but hidden enough that the team must *find* it; branded NFC stickers can be produced at scale and stuck anywhere. Today the only tag mechanic is the shipped **RFID URL capture** (`/tower/rfid/<rfid_code>/`): a plain link that any browser can open. That is a real weakness — the link can be copy-pasted into a group chat or handed to a teammate who never walked to the tag, defeating the "go and find it" premise. This change adds **native NFC scanning** in the mobile player app and a **secure, in-app-only link scheme** where a scanned tag is *only* actionable inside the authenticated app: scanning is the one thing you can do with it, it is single-purpose and non-forwardable. We explicitly accept that a determined attacker with an NFC reader can dump a tag and try to hack it — we raise the bar with app-gating and proximity, not tag secrecy, because most games are cooperative and not adversarial enough for that to matter.

## What Changes

- Introduce a `game.NfcTag` model: a provisioned physical tag bound to a `Tower` (or, for a partner/venue challenge, a `Challenge`), carrying an opaque URL-safe `token`, a capture `mode` (`LEGACY_URL` or `SECURE_TOKEN`), an `is_active` flag, a hidden-location hint (which tree / wall / venue), and optional replay-hardening counters.
- Add a **secure capture endpoint** `POST /api/nfc/capture/` that accepts a scanned `token` plus live GPS from the authenticated app, resolves the tag to a target inside the caller's Session, enforces proximity, checks freshness/replay, and auto-confirms the capture (mirroring RFID) or routes it into the challenge flow.
- Add an **app-link landing** `GET /nfc/<token>/`: when the app opens it, it deep-links into the scan flow; when a plain browser opens it, it returns an "open this in the app" page and performs **no** capture — the enforcement point that makes secure links non-forwardable.
- Write NFC tags as **NDEF** records. In `SECURE_TOKEN` mode the tag carries an app-triggering record (custom URI / Android Application Record) plus the opaque token; in `LEGACY_URL` mode it carries the existing forwardable RFID URL for backward compatibility. Staff can fetch the writable NDEF payload and a printable QR fallback per tag.
- Add **native NFC scanning** to the player SPA: the Web NFC `NDEFReader` where available, a native-shell NFC bridge otherwise, and a QR-scan / manual-code fallback when NFC is unavailable (e.g. iOS browsers). Scanning a tag POSTs its token to the capture endpoint.
- Add per-Game config knobs with nullable per-Session overrides (effective-value pattern): `nfc_secure_mode` (secure token vs legacy URL), `nfc_require_app` (reject browser hits on secure links), and optional `nfc_replay_hardening`. Defaults preserve today's legacy-URL behavior.
- Add a `game.TagScan` audit record (who, when, tag, outcome, GPS, counter) for replay detection and after-game replay/analysis.
- Extend and relate to the existing RFID URL capture: RFID becomes the "legacy convenience" tag mode of a single tag-capture family, and the admin surfaces the NFC payload and QR alongside the printable RFID URL.

## Capabilities

### New Capabilities
- `nfc-capture`: native NFC scanning in the mobile player app and a non-forwardable, single-purpose, app-verified secure-link scheme for tapping physical tags hidden in the game area.

### Modified Capabilities
- `rfid-capture`: the RFID URL becomes the legacy (forwardable) mode of a unified tag-capture family; the admin also surfaces the secure NFC payload and QR fallback; proximity remains enforced.
- `player-app`: the player SPA gains native NFC scanning, secure-link handling, and QR/manual fallbacks; a scanned secure tag is only actionable inside the app.

## Impact

- **Models**: new `game.NfcTag` (token, `mode`, `tower`/`challenge` target, hint, replay counters) and `game.TagScan` (audit); new nullable knobs on `organize.Game` (`nfc_secure_mode`, `nfc_require_app`, `nfc_replay_hardening`) and matching nullable overrides on `organize.Session`.
- **APIs**: new `POST /api/nfc/capture/`; new app-link landing `GET /nfc/<token>/`; new staff `GET/POST/PATCH/DELETE /api/staff/nfc-tags/` with actions to fetch the writable NDEF payload and the printable QR; the shipped `/tower/rfid/<rfid_code>/` route is retained for legacy mode.
- **Frontend**: player SPA gains an NFC scan flow (Web NFC + native bridge + QR/manual fallback) reachable from tower detail; staff/creator SPA gains an NFC-tag provisioning panel with payload/QR export.
- **Migrations/other**: additive migration for the two new models and the new nullable config fields; existing RFID towers keep working unchanged (default `LEGACY_URL`); references the `challenge-types` capability (introduced by the sibling `challenge-type-system` change) for the `NFC_QR` venue/partner challenge type that this capture channel backs.
