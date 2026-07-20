## ADDED Requirements

### Requirement: Submission is the finish phase of the challenge lifecycle

The system SHALL treat a challenge submission as the **finish** phase of the formal identify → initiate → finish lifecycle (see the `tower-locking` capability), where identify serves the next challenge and initiate commits the team to the attempt.

#### Scenario: Finish follows identify and initiate

- **WHEN** a team submits a challenge attempt for a tower
- **THEN** the system SHALL treat the submission as the finish phase that, on confirmation, transfers tower ownership
- **AND** under `FREE_FOR_ALL` a preceding `initiate` call SHALL be optional and the finish SHALL be accepted without one
- **AND** under `LOCK_ON_INITIATE` a finish SHALL be accepted only from the team holding the tower's active lock for its TeamGroup (see the "Authenticated submission with proximity check" requirement)

## MODIFIED Requirements

### Requirement: Authenticated submission with proximity check

The system SHALL accept a challenge submission (the finish phase) only from an authenticated user standing near the tower, deriving the submitting team from the user's active membership, and — under `LOCK_ON_INITIATE` — only from the team that holds the tower's active lock for its TeamGroup.

#### Scenario: Submitting a challenge

- **WHEN** an authenticated user submits an attempt via `POST /api/team_tower_challenges/`
- **THEN** the submission SHALL include the tower, the challenge, the submitter's current GPS position, and optionally a photo
- **AND** the system SHALL derive the team from the authenticated user's active `TeamMembership` and record `submitted_by`
- **AND** the system SHALL create a `TeamTowerChallenge` with outcome `PENDING`

#### Scenario: Rejecting a distant submission

- **WHEN** the submitter's GPS position is farther than the current Session's `proximity_meters` from the tower
- **THEN** the system SHALL reject the submission
- **AND** the threshold SHALL be read from the current Session's Game config (default 50 meters), not hardcoded

#### Scenario: Rejecting a finish from a non-lock-holder under LOCK_ON_INITIATE

- **WHEN** the Session's effective `tower_lock_mode` is `LOCK_ON_INITIATE` and the tower holds an active lock for another team in the submitter's TeamGroup
- **THEN** the system SHALL refuse the submission from any team that is not the active lock holder
- **AND** when the effective mode is `FREE_FOR_ALL` this restriction SHALL NOT apply and simultaneous submissions from multiple teams SHALL be permitted (subject to the rejection cooldown)

### Requirement: Auto-capture on confirmation

The system SHALL automatically capture the tower for the submitting team when a submission is confirmed, and — under `LOCK_ON_INITIATE` — SHALL release that team's active lock as part of the capture.

#### Scenario: Confirming a submission captures the tower

- **WHEN** a `TeamTowerChallenge` transitions to `CONFIRMED`
- **THEN** the system SHALL invoke `tower.assign_to_team(team)`, which closes any prior team's active ownership, opens a new ownership, awards the tower's `initial_bonus`, and triggers zone recalculation (see the `scoring` capability)

#### Scenario: Confirming under LOCK_ON_INITIATE releases the lock

- **WHEN** a `TeamTowerChallenge` transitions to `CONFIRMED` and the Session's effective `tower_lock_mode` is `LOCK_ON_INITIATE`
- **THEN** after the capture the system SHALL release the confirming team's active lock on that tower with `release_reason = FINISHED`
- **AND** the tower SHALL then be available for a new `initiate` by any team in the TeamGroup (see the `tower-locking` capability)
