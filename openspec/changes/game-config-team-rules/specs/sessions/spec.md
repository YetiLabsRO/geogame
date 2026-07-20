## ADDED Requirements

### Requirement: Per-session overrides for team rules

The system SHALL let each Session override any of its Game's team-composition rules, resolving the
effective value as the Session override when set and the Game default otherwise.

#### Scenario: Overriding a threshold for one run

- **WHEN** a Session sets `min_teams`, `max_teams`, `min_members_per_team`, or
  `max_members_per_team` to a non-null value
- **THEN** `Session.effective(field)` SHALL return the Session's value for that field
- **AND** the four field names SHALL be members of `OVERRIDABLE_CONFIG_FIELDS`

#### Scenario: Inheriting when unset

- **WHEN** a Session leaves a team-rule override as `NULL`
- **THEN** `Session.effective(field)` SHALL return the Game default for that field
- **AND** editing these overrides over `POST`/`PATCH /api/staff/sessions/{id}/` SHALL accept a
  blank value as "inherit the Game default"

### Requirement: Start-gating on team composition rules

The system SHALL refuse to move a Session into active play (start / RUNNING — see the
`game-lifecycle` capability) until the number of ready teams is within the effective
`[min_teams, max_teams]` range and every counted team satisfies the effective per-team member
rules, reporting the specific unmet thresholds.

#### Scenario: Refusing to start below the team minimum

- **WHEN** the start action runs on a Session whose count of **ready** teams is below the effective
  `min_teams`
- **THEN** the system SHALL NOT start the Session
- **AND** it SHALL return a blocker naming the required and current team counts

#### Scenario: Under-filled teams do not count toward the minimum

- **WHEN** a Session has `min_teams=2` but only one team meets the effective `min_members_per_team`
  while a second team is under-filled
- **THEN** the start action SHALL treat the under-filled team as not counting toward `min_teams`
  and SHALL NOT start the Session
- **AND** it SHALL return a blocker naming each under-filled team and its member shortfall

#### Scenario: Refusing to start above the team maximum

- **WHEN** the start action runs on a Session whose team count exceeds a non-zero effective
  `max_teams`
- **THEN** the system SHALL NOT start the Session
- **AND** it SHALL return a blocker naming the allowed and current team counts

#### Scenario: Starting when all thresholds are met

- **WHEN** the start action runs on a Session whose ready-team count is within
  `[min_teams, max_teams]` (a `0` maximum meaning "no cap") and every team is ready
- **THEN** `Session.can_start()` SHALL be true and `Session.start_blockers()` SHALL be empty
- **AND** the system SHALL move the Session into active play

#### Scenario: Reporting blockers over the API

- **WHEN** a staff user invokes the Session start action while thresholds are unmet
- **THEN** the system SHALL respond with an error status carrying a machine-readable `blockers`
  list rather than transitioning the Session

#### Scenario: Defaults keep existing runs startable

- **WHEN** a Session runs on a Game left at the default team rules (`min_teams=1`, `max_teams=0`,
  `min_members_per_team=1`, `max_members_per_team=0`)
- **THEN** the start-gate SHALL allow the Session to start as soon as it has one team with at least
  one active member, preserving the pre-change behaviour
