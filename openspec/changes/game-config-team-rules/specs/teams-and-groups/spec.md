## ADDED Requirements

### Requirement: Team readiness against member-count rules

The system SHALL derive, per Team, whether its active-membership count satisfies the effective
per-team member rules of its Session, and MUST NOT let a team grow past the effective maximum.

#### Scenario: Counting active members

- **WHEN** the system evaluates a team's readiness
- **THEN** it SHALL count only that team's `TeamMembership` rows with `is_active=True`
- **AND** it SHALL compare the count against the Session's effective `min_members_per_team` and
  `max_members_per_team` (see the `sessions` and `game-configuration` capabilities), treating a
  maximum of `0` as "no cap"

#### Scenario: A team below the minimum is not ready

- **WHEN** a team has fewer active members than the effective `min_members_per_team`
- **THEN** the team SHALL be reported as **not ready**
- **AND** the shortfall (how many more members are needed) SHALL be available to callers

#### Scenario: A team within range is ready

- **WHEN** a team's active-member count is at least `min_members_per_team` and, when capped, at
  most `max_members_per_team`
- **THEN** the team SHALL be reported as **ready**

#### Scenario: Joining a full team is rejected

- **WHEN** a user attempts to join a team whose active-member count already equals a non-zero
  effective `max_members_per_team` (via invite-accept or an admin add)
- **THEN** the system SHALL reject the join with a clear error and SHALL NOT create the membership

## MODIFIED Requirements

### Requirement: Teams API

The system SHALL expose teams over a REST API for map and scoreboard rendering, including each
team's active-member count and readiness against the effective per-team member rules.

#### Scenario: Listing teams

- **WHEN** a client requests `GET /api/teams/`
- **THEN** the system SHALL return the teams of the caller's current Session, exposing each team's
  `group`

#### Scenario: Reporting member count and readiness

- **WHEN** a client requests `GET /api/teams/`
- **THEN** each team SHALL expose a read-only `active_member_count` and a read-only `is_ready`
  flag computed against the Session's effective `min_members_per_team` and `max_members_per_team`
- **AND** these fields SHALL let a client show how many more members a team needs before its
  Session may start (see the start-gating requirement in the `sessions` capability)
