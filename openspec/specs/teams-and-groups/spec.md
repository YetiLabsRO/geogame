# Teams and Team Groups Specification

## Purpose

Model the competitive roster of an event: Teams and the arbitrarily-named TeamGroups they compete within, so that ownership and leaderboards are partitioned per cohort.

## Requirements

### Requirement: Team groups partition an event

The system SHALL let each Game define zero or more `organize.TeamGroup` rows used to partition its teams (e.g. by age group, by color, or ad hoc).

#### Scenario: Creating a team group

- **WHEN** an administrator creates a team group
- **THEN** it SHALL have a `name`, a URL-safe `slug`, and a `game` foreign key
- **AND** the pair `(game, slug)` SHALL be unique

### Requirement: Team definition

The system SHALL model an `organize.Team` as a competing unit that belongs to one Session and optionally one TeamGroup.

#### Scenario: Creating a team

- **WHEN** an administrator creates a team
- **THEN** the team SHALL belong to exactly one `Session` (see the `sessions` capability) and MAY belong to one `TeamGroup` within that Session's Game
- **AND** the team SHALL allow configuring a display color for map rendering and an optional description

#### Scenario: Team code is retired

- **WHEN** a team is created
- **THEN** the system SHALL NOT issue a shared `team_code` for submission authentication; the legacy `team_code` column has been dropped and submissions are authenticated per-user (see the `user-accounts` and `challenge-submission` capabilities)

### Requirement: Per-group scoring isolation

The system SHALL compute tower ownership, zone ownership, and leaderboards independently per TeamGroup.

#### Scenario: Scoring within a cohort

- **WHEN** the system evaluates zone control or a leaderboard
- **THEN** a team SHALL only be scored against other teams in the same TeamGroup

### Requirement: Teams API

The system SHALL expose teams over a REST API for map and scoreboard rendering.

#### Scenario: Listing teams

- **WHEN** a client requests `GET /api/teams/`
- **THEN** the system SHALL return the teams of the caller's current Session, exposing each team's `group`
