## MODIFIED Requirements

### Requirement: Player SPA scope

The system SHALL provide an Angular player app covering all player-facing functionality, including native NFC scanning and secure-link handling.

#### Scenario: Player routes

- **WHEN** a player uses the app
- **THEN** it SHALL provide auth screens (login, register, password reset, invite-accept), the main map, per-TeamGroup score maps at `/map/<team_group_slug>/`, tower detail, challenge submission, RFID capture, NFC tag scanning, and a rules page
- **AND** it SHALL be built with standalone components, signals, `@if`/`@for` control flow, `input()`/`output()`/`inject()`, and `ChangeDetectionStrategy.OnPush`
- **AND** it SHALL consume the DRF API; Django templates for these routes have been removed

## ADDED Requirements

### Requirement: Player NFC scan flow

The system SHALL let a player scan a physical tag from the app to capture a target, using native NFC where available and falling back gracefully otherwise.

#### Scenario: Scanning from tower detail

- **WHEN** a player opens a tower's detail page for a tag-backed tower
- **THEN** the app SHALL present a "Scan tag" affordance that reads the tag via the Web NFC `NDEFReader` where supported, a native NFC bridge inside a native shell otherwise, and a QR-camera or manual-code fallback when NFC is unavailable
- **AND** on a successful read it SHALL POST the token to `/api/nfc/capture/` with live GPS and show the capture outcome (see the `nfc-capture` capability)

#### Scenario: Proximity feedback during a scan

- **WHEN** the player attempts a scan
- **THEN** the app SHALL show live distance-to-target from device GPS
- **AND** it SHALL surface a clear message when the player is farther than the Session's `proximity_meters`, since the capture will be rejected on the server

### Requirement: Player secure-link handling

The system SHALL make a scanned secure tag actionable only inside the app and guide users who open its link outside the app.

#### Scenario: Opening a secure link outside the app

- **WHEN** a secure tag's app-link `GET /nfc/<token>/` is opened in a plain browser without the app
- **THEN** the player SHALL see an "open this in the app to scan" page and no capture SHALL occur (see the `nfc-capture` capability)

#### Scenario: Deep-linking into the app

- **WHEN** the installed app handles a secure tag's app-link
- **THEN** the app SHALL deep-link directly into the scan flow for that token rather than rendering a web page
