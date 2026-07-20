## ADDED Requirements

### Requirement: Role-gated challenge enforcement

The system SHALL refuse a challenge submission when the submitting team does not satisfy the challenge's role requirement, evaluating the requirement independent of how many members are present.

#### Scenario: Missing a required role

- **WHEN** a team submits a challenge whose `role_requirement_mode` is `ALL` or `ANY` and the team's active role holders do not cover the required roles for that mode (see the `team-roles` capability)
- **THEN** the system SHALL refuse the submission with HTTP 400
- **AND** the error SHALL name the missing roles so the team can reassign roles and retry

#### Scenario: Satisfying the requirement by role, not head-count

- **WHEN** a team's active members cover the challenge's required roles under its mode
- **THEN** the system SHALL accept the submission regardless of how many members are physically present
- **AND** a single member holding every required role SHALL satisfy an `ALL` requirement alone

#### Scenario: No requirement is a no-op

- **WHEN** a challenge's `role_requirement_mode` is `NONE` (the default)
- **THEN** the system SHALL apply no role gate and the submission SHALL proceed exactly as before this change

## MODIFIED Requirements

### Requirement: Authenticated submission with proximity check

The system SHALL accept a challenge submission only from an authenticated user standing near the tower whose team satisfies the challenge's role requirement, deriving the submitting team from the user's active membership.

#### Scenario: Submitting a challenge

- **WHEN** an authenticated user submits an attempt via `POST /api/team_tower_challenges/`
- **THEN** the submission SHALL include the tower, the challenge, the submitter's current GPS position, and optionally a photo
- **AND** the system SHALL derive the team from the authenticated user's active `TeamMembership` and record `submitted_by`
- **AND** the system SHALL verify that the submitting team satisfies the challenge's role requirement (see the `team-roles` capability) before accepting, treating a `role_requirement_mode` of `NONE` as always satisfied
- **AND** the system SHALL create a `TeamTowerChallenge` with outcome `PENDING`

#### Scenario: Rejecting a distant submission

- **WHEN** the submitter's GPS position is farther than the current Session's `proximity_meters` from the tower
- **THEN** the system SHALL reject the submission
- **AND** the threshold SHALL be read from the current Session's Game config (default 50 meters), not hardcoded
