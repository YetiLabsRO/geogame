## ADDED Requirements

### Requirement: Role assignment lives on the roster

The system SHALL let a member's `organize.TeamMembership` hold zero or more of its Game's roles, so in-game roles are a property of the concrete roster of a run and never leak across Sessions.

#### Scenario: A membership holds roles

- **WHEN** roles are assigned to a member
- **THEN** the assignments SHALL attach to that member's `TeamMembership` (see the `team-roles` capability), not to the `Team` or the user globally
- **AND** the roles SHALL respect the membership lifecycle, so only an active membership's roles count toward gameplay

#### Scenario: Roles do not cross Sessions

- **WHEN** a user is a member of teams in more than one Session
- **THEN** the roles held in one Session's team SHALL NOT apply to the user's membership in another Session's team
- **AND** each held role SHALL belong to the Game of the membership that holds it

## MODIFIED Requirements

### Requirement: Teams API

The system SHALL expose teams over a REST API for map and scoreboard rendering, including each member's in-game roles.

#### Scenario: Listing teams

- **WHEN** a client requests `GET /api/teams/`
- **THEN** the system SHALL return the teams of the caller's current Session, exposing each team's `group`
- **AND** each team member's held roles (see the `team-roles` capability) SHALL be exposed alongside the member, so clients can render who holds which role
