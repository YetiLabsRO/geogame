## ADDED Requirements

### Requirement: Native NFC scanning in the player app

The system SHALL let a player capture a tag-backed target by tapping their phone to a physical NFC tag using native NFC, with a graceful fallback where NFC is unavailable.

#### Scenario: Scanning with Web NFC

- **WHEN** a player on a platform that supports the Web NFC `NDEFReader` taps a provisioned NFC tag from the tower detail scan flow
- **THEN** the app SHALL read the tag's NDEF token and POST it to the capture endpoint (see the "Secure capture endpoint" requirement)
- **AND** the app SHALL show live proximity feedback and the capture outcome

#### Scenario: Scanning through a native shell

- **WHEN** the player app is running inside a native shell (for platforms without in-browser Web NFC, such as iOS)
- **THEN** the app SHALL read the tag through a native NFC bridge and MUST route the same token through the same capture endpoint

#### Scenario: Fallback when NFC is unavailable

- **WHEN** the device or browser cannot scan NFC
- **THEN** the app SHALL offer a QR-code camera scan and a manual code-entry fallback
- **AND** each fallback SHALL resolve to the same token so the backend capture path is identical regardless of transport

### Requirement: In-app-only, non-forwardable secure links

The system SHALL make a scanned secure tag actionable only inside the authenticated app, so a tag's contents cannot be copy-pasted into a browser or forwarded to be actioned elsewhere.

#### Scenario: Plain browser cannot capture

- **WHEN** a person opens the tag's app-link `GET /nfc/<token>/` in a plain web browser without the app
- **THEN** the system SHALL return an "open this in the app to scan" page
- **AND** it SHALL NOT perform any capture

#### Scenario: App deep-links into the scan flow

- **WHEN** the installed app handles the app-link (Android App Link / iOS Universal Link) for a tag
- **THEN** the app SHALL deep-link into the scan flow for that token rather than rendering a web page

#### Scenario: Forwarded token without presence fails

- **WHEN** a token is forwarded to another player and submitted without the sender being physically at the tag
- **THEN** the capture SHALL be rejected because the submitter fails the proximity check, and the attempt SHALL be recorded in the scan audit

### Requirement: NFC tag provisioning and payload export

The system SHALL model provisioned physical tags and let staff mint them at scale, bind them to a target, and export what to write to the tag.

#### Scenario: Modeling a tag

- **WHEN** staff create a `game.NfcTag`
- **THEN** it SHALL carry an opaque URL-safe `token`, a `mode` of `LEGACY_URL` or `SECURE_TOKEN`, an `is_active` flag, a `hidden_hint` describing where it is concealed (e.g. inside a tree, behind wall plaster), and exactly one target that is either a `Tower` or a `Challenge`
- **AND** a `SECURE_TOKEN` tag's token SHALL be meaningless on its own, actionable only through the capture endpoint

#### Scenario: Exporting the writable payload

- **WHEN** staff request the writable payload for a tag over `GET/POST/PATCH/DELETE /api/staff/nfc-tags/`
- **THEN** the system SHALL return the NDEF payload to write — for `SECURE_TOKEN`, an app-triggering record (custom URI plus an Android Application Record) and the token; for `LEGACY_URL`, the existing `/tower/rfid/<rfid_code>/` URL (see the `rfid-capture` capability)
- **AND** it SHALL also return a printable QR image encoding the same app-link for branded stickers and camera fallback

### Requirement: Secure capture endpoint

The system SHALL expose an authenticated endpoint that turns a scanned token into a capture only when the request comes from the app with live location inside the caller's Session.

#### Scenario: Valid scan near the tag

- **WHEN** the authenticated app POSTs `{token, lat, lng, accuracy}` to `/api/nfc/capture/` and the tag's target is reachable through the caller's current Session's collections and the submitter is within the Session's `proximity_meters`
- **THEN** the system SHALL, for a tower target, auto-confirm the capture with outcome `CONFIRMED` and reassign the tower exactly as an RFID capture does (see the `rfid-capture` capability)
- **AND** for a challenge target it SHALL route the scan into the challenge-submission flow (see the `challenge-types` capability)

#### Scenario: Out-of-scope token rejected

- **WHEN** the token resolves to a target not reachable through the caller's current Session's collections, or the tag is inactive
- **THEN** the system SHALL reject the capture and SHALL NOT change any ownership

#### Scenario: Every scan is audited

- **WHEN** any capture attempt reaches the endpoint
- **THEN** the system SHALL write a `game.TagScan` record with the tag, submitter, Session, timestamp, outcome, GPS, and any counter, for replay detection and after-game analysis

### Requirement: Capture-mode configuration

The system SHALL make secure-link behavior configurable per Game with a nullable per-Session override, defaulting to the legacy forwardable behavior so existing games are unchanged.

#### Scenario: Effective value resolution

- **WHEN** the system resolves `nfc_secure_mode`, `nfc_require_app`, or `nfc_replay_hardening` for a running Session
- **THEN** a non-null Session override SHALL win, otherwise the Game default SHALL apply
- **AND** when unset, the effective behavior SHALL preserve today's legacy RFID URL capture (see the `rfid-capture` capability)

#### Scenario: Requiring the app

- **WHEN** `nfc_require_app` is enabled for the Session
- **THEN** the endpoint SHALL require the app-origin signal and reject captures that present as raw browser hits, while still enforcing auth and proximity as the real boundary

### Requirement: Accepted threat model

The system SHALL treat a tag's contents as extractable and forgeable, and SHALL rely on app-gating, proximity, and audit rather than tag secrecy for integrity.

#### Scenario: Documented accepted risk

- **WHEN** the capability is reasoned about for security
- **THEN** the design SHALL document that a motivated attacker with an NFC reader can dump a tag's token and attempt to replay or clone it, and that this is accepted for cooperative, low-stakes games
- **AND** the system SHALL NOT claim cryptographic unforgeability of a tag

#### Scenario: Opt-in hardening for adversarial games

- **WHEN** a game enables `nfc_replay_hardening`
- **THEN** the system SHALL require a monotonically increasing tag counter and SHALL reject a repeated or lower counter as a replay
- **AND** with hardening off, the system SHALL accept static tokens so cheap static tags remain usable
