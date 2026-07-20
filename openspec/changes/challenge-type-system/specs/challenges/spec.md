## MODIFIED Requirements

### Requirement: Challenge definition

The system SHALL model a `game.Challenge` with a `type`, text content, and a difficulty level, either bound to a specific tower or reusable as a generic challenge, where the `type` determines the challenge's validation payload and review flow.

#### Scenario: Creating a challenge

- **WHEN** an administrator creates a challenge
- **THEN** it SHALL carry a `type` of `TEXT`, `PHOTO`, `NFC_QR`, or `RFID` (see the `challenge-types` capability), defaulting to `TEXT`
- **AND** it SHALL have text content and an integer difficulty level (typically 1-5)
- **AND** it SHALL either be bound to a specific tower (tower-specific) or be generic (reusable across any tower)
- **AND** it SHALL carry a `game` foreign key so it is shared across every Session of that Game

#### Scenario: Type-specific configuration

- **WHEN** a challenge's `type` requires extra configuration
- **THEN** an `NFC_QR` challenge SHALL carry a `validation_code` (the code handed out at the venue) and a `type_config` for per-type extras such as the partner/venue label and a `single_use` flag
- **AND** a challenge MAY carry a `review_mode` override that supersedes its type's default review flow (see the `challenge-types` capability)
- **AND** a `TEXT` challenge SHALL require no type-specific configuration and behave identically to a pre-change text challenge

### Requirement: Next-challenge selection

The system SHALL serve the correct next challenge for the tower a team is standing at, based on the highest difficulty that team has already conquered at that tower, independent of challenge type.

#### Scenario: Selection order

- **WHEN** a team requests the next challenge for a tower
- **THEN** the system SHALL select, in order:
  1. the lowest-difficulty tower-specific challenge not yet conquered, then
  2. generic challenges in ascending difficulty, then
  3. once all are exhausted, the hardest generic challenge as an infinite replay fallback
- **AND** the selection SHALL order only by difficulty and the tower-specific-then-generic rule, ignoring the challenge's `type`, so a tower MAY mix types across difficulty buckets

#### Scenario: Progression is per-tower

- **WHEN** the next challenge is computed
- **THEN** the calculation SHALL be based on the highest difficulty the team has already conquered at that specific tower

### Requirement: Challenges API

The system SHALL expose challenges over a REST API, including each challenge's type and the submission payload it expects.

#### Scenario: Listing challenges

- **WHEN** a client requests `GET /api/challenges/`
- **THEN** the system SHALL return the current Session's Game challenges, including both tower-specific and generic challenges of every type
- **AND** each challenge SHALL report its `type`, its effective review mode, and the payload a submission must supply, without exposing an `NFC_QR` challenge's raw `validation_code` to players
