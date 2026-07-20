## ADDED Requirements

### Requirement: Challenge type taxonomy

The system SHALL give every `game.Challenge` a `type` that determines the submission payload it requires and how the submission is reviewed, drawn from a fixed set of types each mapped to a handler.

#### Scenario: The four shipped types

- **WHEN** a challenge is authored
- **THEN** its `type` SHALL be one of `TEXT` (a location-based text question), `PHOTO` (photo evidence), `NFC_QR` (a code scanned at a partner venue), or `RFID` (a scanned tower tag)
- **AND** the `type` SHALL default to `TEXT`
- **AND** each type SHALL declare a review flow of either `AUTO` (validated by the system) or `MANUAL` (validated by staff)

#### Scenario: Type defaults preserve current behavior

- **WHEN** a challenge is created without specifying a `type`
- **THEN** the system SHALL treat it as `TEXT`
- **AND** a `TEXT` challenge SHALL behave identically to a pre-change text challenge — location-based, staff-reviewed, and captured on confirmation (see the `challenges` and `challenge-submission` capabilities)

### Requirement: Pluggable challenge-type handler registry

The system SHALL resolve each challenge's validation and review flow through a handler registry keyed by `type`, so a new type is added by registering a handler rather than by editing the submission pipeline.

#### Scenario: Dispatching a submission by type

- **WHEN** a submission is made for a challenge of a given `type`
- **THEN** the system SHALL look up the handler registered for that `type`
- **AND** the handler SHALL declare its `review_mode` (`AUTO` or `MANUAL`) and the payload the submission must supply
- **AND** the submission pipeline SHALL delegate validation to that handler rather than branching on the type inline

#### Scenario: Unknown type is rejected safely

- **WHEN** a submission references a challenge whose `type` has no registered handler
- **THEN** the system SHALL reject the submission
- **AND** it SHALL NOT capture the tower or record a `CONFIRMED` outcome

### Requirement: Auto-validated types confirm on a matching code

The system SHALL, for the `AUTO` review types (`NFC_QR` and `RFID`), confirm a submission automatically when its scanned code matches the challenge's expected code and the proximity check passes, and reject it otherwise.

#### Scenario: A matching scan auto-confirms

- **WHEN** a team submits a `submitted_code` for an `NFC_QR` or `RFID` challenge and the code matches the expected code
- **AND** the submitter is within the Session's `proximity_meters` of the tower
- **THEN** the system SHALL set the outcome to `CONFIRMED` immediately without staff review
- **AND** it SHALL capture the tower for the team via the existing auto-capture path (see the `challenge-submission` capability)

#### Scenario: A wrong code auto-rejects and feeds the cooldown

- **WHEN** a submitted code does not match the expected code
- **THEN** the system SHALL set the outcome to `REJECTED` immediately
- **AND** the rejection SHALL count toward the per-tower rejection cooldown (see the `challenge-submission` capability)

### Requirement: Manual-review types enter the staff review flow

The system SHALL, for the `MANUAL` review types (`TEXT` and `PHOTO`), create the submission as `PENDING` and route it to the existing staff confirm/reject surface unchanged.

#### Scenario: A photo submission awaits review

- **WHEN** a team submits a `PHOTO` challenge with a photo from within proximity
- **THEN** the system SHALL create the submission with outcome `PENDING`
- **AND** staff SHALL confirm or reject it exactly as they review text challenges today (see the `challenge-submission` capability)

#### Scenario: A photo type requires a photo

- **WHEN** a `PHOTO` challenge is submitted without a photo
- **THEN** the system SHALL reject the submission before it reaches review

### Requirement: NFC/QR venue validation

The system SHALL let an `NFC_QR` challenge validate a real-world action at a partner venue by matching a code the venue hands out, with optional single-use consumption of that code.

#### Scenario: Scanning the venue's code captures the tower

- **WHEN** a challenge of type `NFC_QR` carries a `validation_code` and per-type `type_config` (e.g. a partner/venue label)
- **AND** a team, standing at the tower, submits the `validation_code` the venue handed them
- **THEN** the system SHALL auto-confirm the submission and capture the tower
- **AND** the raw `validation_code` SHALL NOT be exposed to players through the challenge API

#### Scenario: Single-use codes are consumed

- **WHEN** an `NFC_QR` challenge's `type_config` sets `single_use` to true
- **THEN** the system SHALL consume the `validation_code` on the first successful confirmation
- **AND** it SHALL reject any later submission that re-uses the consumed code
- **AND** when `single_use` is false (the default) the system SHALL allow every team to validate with the same code

### Requirement: Per-challenge review-mode override

The system SHALL let a challenge override its type's default review mode without changing its type, so an otherwise auto-validated challenge MAY be forced to manual review.

#### Scenario: Forcing an auto type to manual review

- **WHEN** an `NFC_QR` challenge sets `review_mode` to `MANUAL`
- **AND** a team submits a matching code
- **THEN** the system SHALL create the submission as `PENDING` for staff review rather than auto-confirming
- **AND** the effective review mode SHALL be `challenge.review_mode` when set, else the handler's default
