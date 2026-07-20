## MODIFIED Requirements

### Requirement: RFID capture route

The system SHALL expose a public route that resolves an RFID code to its tower and auto-confirms a capture, retained as the legacy convenience mode of a unified tag-capture family whose non-forwardable, app-only alternative is provided by the `nfc-capture` capability.

#### Scenario: Scanning an RFID tag

- **WHEN** a player opens `/tower/rfid/<rfid_code>/`
- **THEN** the system SHALL resolve the matching tower by its `rfid_code`
- **AND** the capture SHALL NOT require a text challenge and SHALL auto-confirm (outcome `CONFIRMED`), immediately assigning the tower to the team

#### Scenario: Proximity still enforced on scan

- **WHEN** an RFID capture is attempted
- **THEN** the system SHALL still validate that the submitter is within the Session's `proximity_meters` of the tower before confirming

#### Scenario: Legacy URL is forwardable by design

- **WHEN** a game needs a tag whose scan cannot be copy-pasted or forwarded out of the app
- **THEN** the RFID URL mode SHALL be understood as forwardable (any browser can open it), and the game SHALL instead use the secure, app-only token mode defined by the `nfc-capture` capability
- **AND** the RFID URL route SHALL remain the default so existing games are unchanged

### Requirement: Printable RFID URL in admin

The system SHALL surface each RFID tower's capture payloads to staff for producing tags, including both the legacy printable URL and the secure NFC payload.

#### Scenario: Viewing the RFID URL

- **WHEN** a staff member views an RFID-category tower in the Django admin
- **THEN** the admin SHALL display a clickable URL built from the tower's `rfid_code`

#### Scenario: Viewing the secure NFC payload

- **WHEN** a staff member views an RFID-category tower that also has a provisioned secure tag
- **THEN** the admin SHALL additionally surface the writable NFC NDEF payload and a printable QR fallback (see the `nfc-capture` capability)
- **AND** it SHALL indicate which capture mode (`LEGACY_URL` or `SECURE_TOKEN`) the tower uses
