## ADDED Requirements

### Requirement: Team-count and team-size rule configuration

The system SHALL let each Game configure how many teams a run needs and how many members each
team needs, as per-Game defaults read for the current Session, so competitive games can require
multiple teams while single-team variants remain playable.

#### Scenario: Configurable team-rule fields

- **WHEN** gameplay or the start-gate reads a team-composition threshold
- **THEN** it SHALL read `min_teams`, `max_teams`, `min_members_per_team`, and
  `max_members_per_team` from the current Session's Game config (resolved through the effective
  value helper — see the `sessions` capability)
- **AND** `max_teams` and `max_members_per_team` SHALL treat the value `0` as "no maximum"
- **AND** `min_teams` and `min_members_per_team` SHALL be at least `1`

#### Scenario: Defaults preserve single-team play

- **WHEN** a Game is created without setting the team-rule fields
- **THEN** the defaults SHALL be `min_teams=1`, `max_teams=0`, `min_members_per_team=1`, and
  `max_members_per_team=0`
- **AND** a Session on that Game SHALL be startable with a single team of one member, exactly as
  before this change

#### Scenario: Requiring a competitive minimum

- **WHEN** a creator sets `min_teams` to `2` (or higher) on a Game
- **THEN** every Session on that Game SHALL require at least that many ready teams before it may
  start (see the start-gating requirement in the `sessions` capability)

#### Scenario: Editing the rules over the games API

- **WHEN** a staff user calls `POST /api/staff/games/` or `PATCH /api/staff/games/{id}/` with any
  of the four team-rule fields
- **THEN** the system SHALL persist them on the Game
- **AND** it SHALL reject a `min_teams` or `min_members_per_team` below `1`, and reject a non-zero
  maximum that is smaller than its corresponding minimum
