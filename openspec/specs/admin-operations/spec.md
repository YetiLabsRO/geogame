# Admin Operations Specification

## Purpose

Provide rich Django admin screens so staff can monitor and manage the game without a custom dashboard, complementing the staff SPA for rare operations.

## Requirements

### Requirement: Zone and Tower admin

The system SHALL provide admin screens for zones and towers with ownership visibility and management actions.

#### Scenario: Zone admin

- **WHEN** a staff member opens the Zone admin
- **THEN** the list SHALL be color-coded and show the current per-TeamGroup controller

#### Scenario: Tower admin

- **WHEN** a staff member opens the Tower admin
- **THEN** the list SHALL be filterable by zone, active, and category (NORMAL vs RFID)
- **AND** it SHALL show the current owner per TeamGroup and expose `initial_bonus`, `decrease_initial_bonus`, `rfid_code`, and a public RFID URL
- **AND** setting `zone` unset on save with `autocreate_zone` SHALL create a circle zone

### Requirement: Team and Game admin

The system SHALL provide admin screens for teams, games, and team groups.

#### Scenario: Team admin

- **WHEN** a staff member opens the Team admin
- **THEN** the list SHALL be filterable by `group` and shows `score` (readonly) and real-time `floating_score`

#### Scenario: Game admin

- **WHEN** a staff member opens the Game admin
- **THEN** it SHALL provide standard CRUD for `organize.Game`, with `TeamGroup` managed via smart_selects chained dropdowns (Team.group depends on Team's Game)

### Requirement: Challenge and submission admin

The system SHALL provide admin screens for challenges and submissions with review metadata.

#### Scenario: Challenge admin

- **WHEN** a staff member opens the Challenge admin
- **THEN** it SHALL show counts of total attempts and successful confirmations per challenge

#### Scenario: Submission admin

- **WHEN** a staff member opens the TeamTowerChallenge admin
- **THEN** the list SHALL be filterable by outcome, submitter, and reviewer
- **AND** it SHALL show the photo, response text, verified timestamp, and time-to-verify as readonly columns
