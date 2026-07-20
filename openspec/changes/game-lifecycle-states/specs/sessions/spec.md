## MODIFIED Requirements

### Requirement: Session definition

The system SHALL model `organize.Session` as a single live run of a Game, owning its teams, ownerships, clock, and a formal lifecycle `state`.

#### Scenario: Session fields

- **WHEN** a Session is created
- **THEN** it SHALL have a `game` foreign key, `slug` (unique within the Game), `name`, `start_time`, `end_time`, an optional `scheduled_start`, a lifecycle `state`, `created_by`, and `created_at`
- **AND** the pair `(game, slug)` SHALL be unique
- **AND** each Session SHALL run its own clock
- **AND** `state` SHALL be the source of truth for the lifecycle, one of `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, or `FINISHED` (see the `session-lifecycle` capability), defaulting to `DRAFT`

#### Scenario: Active flag is derived from state

- **WHEN** any consumer reads `Session.is_active`
- **THEN** the system SHALL derive it as `True` when `state` is `OPEN_FOR_PARTICIPANTS`, `RUNNING`, or `PAUSED`, and `False` when `state` is `DRAFT` or `FINISHED`
- **AND** `is_active` SHALL be a read-only derived property rather than an independently writable column

#### Scenario: Finishing a session preserves history

- **WHEN** a Session transitions to the terminal `FINISHED` state (see the `session-lifecycle` capability)
- **THEN** it SHALL be hidden from active player and scoreboard views
- **AND** all ownership records SHALL be preserved and remain visible in history

### Requirement: Current session selection

The system SHALL let each user select which Session they are currently playing or administering, and scope views to it.

#### Scenario: Reading and writing the current session

- **WHEN** a client calls `GET` or `POST /api/current-session/`
- **THEN** the system SHALL read or write `UserProfile.current_session` and return the Session together with its nested Game config and its lifecycle `state`

#### Scenario: Player default selection

- **WHEN** a player has exactly one active `TeamMembership` whose `team.session` is active (derived `is_active`, i.e. `state` in `OPEN_FOR_PARTICIPANTS`, `RUNNING`, or `PAUSED`)
- **THEN** the system SHALL auto-select that Session as the current one; otherwise it SHALL prompt the player to pick

### Requirement: Sessions CRUD API

The system SHALL let staff manage Sessions over a REST API and drive their lifecycle through explicit transition actions.

#### Scenario: Creating and editing a session

- **WHEN** a staff user calls `POST /api/staff/sessions/` or `PATCH /api/staff/sessions/{id}/`
- **THEN** the system SHALL create a Session under a chosen Game or edit its name, slug, dates, and `scheduled_start`
- **AND** the lifecycle `state` SHALL NOT be edited by arbitrary write; it SHALL change only through the lifecycle transition actions (see the `session-lifecycle` capability)

#### Scenario: Finishing closes ownerships

- **WHEN** a Session is finished through the `finish` lifecycle action
- **THEN** the system SHALL close all open ownerships on that Session (see the `game-lifecycle` capability) while preserving history
