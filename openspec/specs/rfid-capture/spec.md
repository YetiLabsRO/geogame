# RFID Tower Capture Specification

## Purpose

Let players capture an RFID-tagged tower by scanning its tag, treating physical tag presence (plus GPS proximity) as sufficient proof of capture.

## Requirements

### Requirement: RFID capture route

The system SHALL expose a public route that resolves an RFID code to its tower and auto-confirms a capture.

#### Scenario: Scanning an RFID tag

- **WHEN** a player opens `/tower/rfid/<rfid_code>/`
- **THEN** the system SHALL resolve the matching tower by its `rfid_code`
- **AND** the capture SHALL NOT require a text challenge and SHALL auto-confirm (outcome `CONFIRMED`), immediately assigning the tower to the team

#### Scenario: Proximity still enforced on scan

- **WHEN** an RFID capture is attempted
- **THEN** the system SHALL still validate that the submitter is within the Session's `proximity_meters` of the tower before confirming

### Requirement: Printable RFID URL in admin

The system SHALL surface each RFID tower's public capture URL to staff for printing tag stickers.

#### Scenario: Viewing the RFID URL

- **WHEN** a staff member views an RFID-category tower in the Django admin
- **THEN** the admin SHALL display a clickable URL built from the tower's `rfid_code`
