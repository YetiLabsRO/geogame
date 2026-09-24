## MODIFIED Requirements

### Requirement: Staff SPA scope

The system SHALL provide a staff app for the most common operational tasks, gated to staff users.

#### Scenario: Staff capabilities

- **WHEN** a staff user opens the app
- **THEN** it SHALL provide a pending review queue, tower/zone/team CRUD, challenge management, invite management, a live scoreboard, Game/Session management panels, session replay, and the game simulator
- **AND** access SHALL be gated behind `is_staff=True`
- **AND** a visible "Django Admin" link SHALL remain for rare operations the staff UI does not cover

## ADDED Requirements

### Requirement: Replay and simulator are reachable from the staff app

The system SHALL give staff a direct route to replay a Session and to run a simulation, without leaving the staff app.

#### Scenario: Reaching a session's replay

- **WHEN** a staff user is viewing a Session
- **THEN** the app SHALL offer a link to that Session's replay
- **AND** the replay SHALL open on the map-and-timeline view described by the `session-replay` capability

#### Scenario: The former location-history route

- **WHEN** a staff user follows a previously-bookmarked link to a Session's location history
- **THEN** the app SHALL take them to that Session's replay rather than failing
