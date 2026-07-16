# Sessions Specification

## Purpose

Define the `Session` as one live run of a Game with a specific roster. Teams belong to a Session, so the same physical course can run for two rosters at once as two Sessions sharing one Game. Covers session selection, scoping, and per-game membership uniqueness.

## Requirements

### Requirement: Session definition

The system SHALL model `organize.Session` as a single live run of a Game, owning its teams, ownerships, and clock.

#### Scenario: Session fields

- **WHEN** a Session is created
- **THEN** it SHALL have a `game` foreign key, `slug` (unique within the Game), `name`, `start_time`, `end_time`, `is_active`, `created_by`, and `created_at`
- **AND** the pair `(game, slug)` SHALL be unique
- **AND** each Session SHALL run its own clock

#### Scenario: Deactivating a session preserves history

- **WHEN** a Session's `is_active` is set to `False`
- **THEN** it SHALL be hidden from active player and scoreboard views
- **AND** all ownership records SHALL be preserved and remain visible in history

### Requirement: Current session selection

The system SHALL let each user select which Session they are currently playing or administering, and scope views to it.

#### Scenario: Reading and writing the current session

- **WHEN** a client calls `GET` or `POST /api/current-session/`
- **THEN** the system SHALL read or write `UserProfile.current_session` and return the Session together with its nested Game config

#### Scenario: Player default selection

- **WHEN** a player has exactly one active `TeamMembership` whose `team.session.is_active` is true
- **THEN** the system SHALL auto-select that Session as the current one; otherwise it SHALL prompt the player to pick

### Requirement: Session and game scoping

The system SHALL filter every data view by the caller's current Session (or its Game).

#### Scenario: Scoped viewsets

- **WHEN** a request is served by a session-scoped viewset (teams, ownerships, submissions)
- **THEN** results SHALL be filtered by `request.user.profile.current_session`
- **AND** game-scoped viewsets (zones, towers, challenges, team groups) SHALL be filtered by `request.user.profile.current_session.game`

### Requirement: One active membership per game

The system SHALL prevent a user from holding two active memberships within the same Game, while allowing concurrent memberships across different Games.

#### Scenario: Enforcing uniqueness

- **WHEN** a `TeamMembership` is created or updated
- **THEN** it SHALL carry a denormalized `game` foreign key sourced from `team.session.game`
- **AND** a unique constraint SHALL prevent two active memberships (`is_active=True`) for the same `(user, game)` pair
- **AND** invite-accept and admin flows SHALL surface a clear error when the constraint would be violated

### Requirement: Sessions CRUD API

The system SHALL let staff manage Sessions over a REST API.

#### Scenario: Creating and editing a session

- **WHEN** a staff user calls `POST /api/staff/sessions/` or `PATCH /api/staff/sessions/{id}/`
- **THEN** the system SHALL create a Session under a chosen Game or edit its name, slug, dates, and active flag

#### Scenario: Deactivation closes ownerships

- **WHEN** a Session is deactivated through the API
- **THEN** the system SHALL close all open ownerships on that Session (see the `game-lifecycle` capability) while preserving history
