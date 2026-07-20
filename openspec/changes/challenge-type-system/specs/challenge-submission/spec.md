## ADDED Requirements

### Requirement: Type-dispatched submission validation

The system SHALL validate every submission through the handler registered for its challenge's `type`, applying the proximity check and per-tower cooldown to all types and branching the outcome by the type's review mode.

#### Scenario: Auto types resolve on submission

- **WHEN** a submission is made for an `AUTO`-review type (`NFC_QR` or `RFID`) with a `submitted_code`
- **THEN** the system SHALL resolve the type's handler and check the `submitted_code` against the expected code plus the proximity check
- **AND** a match SHALL set outcome `CONFIRMED` and capture the tower inline, while a mismatch SHALL set outcome `REJECTED`
- **AND** an auto outcome SHALL be attributed to the system rather than to a reviewing staff user

#### Scenario: Manual types stay pending

- **WHEN** a submission is made for a `MANUAL`-review type (`TEXT` or `PHOTO`)
- **THEN** the system SHALL create the submission with outcome `PENDING` and route it to staff review unchanged

## MODIFIED Requirements

### Requirement: Authenticated submission with proximity check

The system SHALL accept a challenge submission only from an authenticated user standing near the tower, deriving the submitting team from the user's active membership, and SHALL collect the payload required by the challenge's type.

#### Scenario: Submitting a challenge

- **WHEN** an authenticated user submits an attempt via `POST /api/team_tower_challenges/`
- **THEN** the submission SHALL include the tower, the challenge, and the submitter's current GPS position
- **AND** it SHALL include the payload the challenge's `type` requires: a photo for `PHOTO`, a `submitted_code` for `NFC_QR` and `RFID`, and none for `TEXT` (see the `challenge-types` capability)
- **AND** the system SHALL derive the team from the authenticated user's active `TeamMembership` and record `submitted_by`
- **AND** the system SHALL create a `TeamTowerChallenge` whose outcome is `PENDING` for manual-review types or the resolved `CONFIRMED`/`REJECTED` for auto-review types

#### Scenario: Rejecting a distant submission

- **WHEN** the submitter's GPS position is farther than the current Session's `proximity_meters` from the tower
- **THEN** the system SHALL reject the submission regardless of challenge type
- **AND** the threshold SHALL be read from the current Session's Game config (default 50 meters), not hardcoded

### Requirement: Staff review of submissions

The system SHALL let staff confirm or reject pending submissions of manual-review types, recording who reviewed and when, while auto-review submissions bypass this surface with a system-attributed outcome.

#### Scenario: Recording a review

- **WHEN** a staff member confirms or rejects a pending manual-review submission
- **THEN** the submission's outcome SHALL move from `PENDING` to `CONFIRMED` or `REJECTED`
- **AND** the system SHALL record the reviewing user (`checked_by`), the `verified_at` timestamp, and an optional `response_text`
- **AND** the review surface SHALL expose a `time_diff` (seconds between submission and verification), the photo, and the response text

#### Scenario: Auto outcomes appear as audit rows

- **WHEN** an auto-review submission (`NFC_QR` or `RFID`) resolves to `CONFIRMED` or `REJECTED`
- **THEN** the system SHALL NOT place it in the pending-review queue
- **AND** it SHALL remain visible as a read-only audit row recording the `submitted_code` and the resolved outcome

### Requirement: Auto-capture on confirmation

The system SHALL automatically capture the tower for the submitting team when a submission is confirmed, whether the confirmation is by staff (manual types) or by the system (auto types).

#### Scenario: Confirming a submission captures the tower

- **WHEN** a `TeamTowerChallenge` transitions to `CONFIRMED`, by staff review or by an auto-validated scan
- **THEN** the system SHALL invoke `tower.assign_to_team(team)`, which closes any prior team's active ownership, opens a new ownership, awards the tower's `initial_bonus`, and triggers zone recalculation (see the `scoring` capability)
