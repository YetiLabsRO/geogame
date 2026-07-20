## MODIFIED Requirements

### Requirement: RFID capture route

The system SHALL expose a public route that resolves an RFID code to its tower and auto-confirms a capture, formalized as the `RFID` challenge type sharing the auto-validated review path (see the `challenge-types` capability).

#### Scenario: Scanning an RFID tag

- **WHEN** a player opens `/tower/rfid/<rfid_code>/`
- **THEN** the system SHALL resolve the matching tower by its `rfid_code`
- **AND** the capture SHALL be handled by the `RFID` challenge-type handler, which treats the tower's `rfid_code` as the expected code
- **AND** the capture SHALL NOT require a text challenge and SHALL auto-confirm (outcome `CONFIRMED`), immediately assigning the tower to the team

#### Scenario: Proximity still enforced on scan

- **WHEN** an RFID capture is attempted
- **THEN** the system SHALL still validate that the submitter is within the Session's `proximity_meters` of the tower before confirming

#### Scenario: Parity with a built RFID submission

- **WHEN** an `RFID`-type submission is built directly against the tower with the tower's `rfid_code` as its `submitted_code`
- **THEN** it SHALL reach the same auto-confirm outcome as the `/tower/rfid/<rfid_code>/` route
- **AND** `Tower.category == RFID` SHALL remain the trigger that routes capture through the `RFID` handler

### Requirement: Printable RFID URL in admin

The system SHALL surface each RFID tower's public capture URL to staff for printing tag stickers, alongside the analogous handout code for `NFC_QR` challenges.

#### Scenario: Viewing the RFID URL

- **WHEN** a staff member views an RFID-category tower in the Django admin
- **THEN** the admin SHALL display a clickable URL built from the tower's `rfid_code`

#### Scenario: Viewing an NFC/QR handout code

- **WHEN** a staff member views an `NFC_QR` challenge in the Django admin
- **THEN** the admin SHALL surface its `validation_code` in a printable/handout form so venue staff can distribute it (see the `challenge-types` capability)
