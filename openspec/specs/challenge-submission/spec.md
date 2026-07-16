# Challenge Submission & Review Specification

## Purpose

Define how an authenticated player submits a challenge attempt from a tower's physical location, how staff review it, the cooldown after a rejection, and the automatic tower capture on confirmation.

## Requirements

### Requirement: Authenticated submission with proximity check

The system SHALL accept a challenge submission only from an authenticated user standing near the tower, deriving the submitting team from the user's active membership.

#### Scenario: Submitting a challenge

- **WHEN** an authenticated user submits an attempt via `POST /api/team_tower_challenges/`
- **THEN** the submission SHALL include the tower, the challenge, the submitter's current GPS position, and optionally a photo
- **AND** the system SHALL derive the team from the authenticated user's active `TeamMembership` and record `submitted_by`
- **AND** the system SHALL create a `TeamTowerChallenge` with outcome `PENDING`

#### Scenario: Rejecting a distant submission

- **WHEN** the submitter's GPS position is farther than the current Session's `proximity_meters` from the tower
- **THEN** the system SHALL reject the submission
- **AND** the threshold SHALL be read from the current Session's Game config (default 50 meters), not hardcoded

### Requirement: Cooldown after a rejected attempt

The system SHALL enforce a per-tower cooldown after a rejected attempt to discourage guessing.

#### Scenario: Blocking during cooldown

- **WHEN** a team's most recent attempt on a tower was `REJECTED` within the Session's `cooloff_minutes` window
- **THEN** the system SHALL refuse new submissions from that team on that tower until the cooldown expires
- **AND** the cooldown duration SHALL be read from the current Session's Game config (default 5 minutes), not hardcoded

### Requirement: Staff review of submissions

The system SHALL let staff confirm or reject pending submissions, recording who reviewed and when.

#### Scenario: Recording a review

- **WHEN** a staff member confirms or rejects a submission
- **THEN** the submission's outcome SHALL move from `PENDING` to `CONFIRMED` or `REJECTED`
- **AND** the system SHALL record the reviewing user (`checked_by`), the `verified_at` timestamp, and an optional `response_text`
- **AND** the review surface SHALL expose a `time_diff` (seconds between submission and verification), the photo, and the response text

### Requirement: Auto-capture on confirmation

The system SHALL automatically capture the tower for the submitting team when a submission is confirmed.

#### Scenario: Confirming a submission captures the tower

- **WHEN** a `TeamTowerChallenge` transitions to `CONFIRMED`
- **THEN** the system SHALL invoke `tower.assign_to_team(team)`, which closes any prior team's active ownership, opens a new ownership, awards the tower's `initial_bonus`, and triggers zone recalculation (see the `scoring` capability)
