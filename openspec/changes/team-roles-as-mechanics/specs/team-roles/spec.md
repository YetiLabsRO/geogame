## ADDED Requirements

### Requirement: Per-Game role definitions

The system SHALL let a creator define an arbitrary set of roles per Game as `organize.GameRole` rows, so roles are part of a Game's authored rule set rather than a fixed, global list.

#### Scenario: Defining a role

- **WHEN** a creator defines a role on a Game
- **THEN** the role SHALL have a `name`, a URL-safe `slug`, an optional `description`, and a `game` foreign key
- **AND** the pair `(game, slug)` SHALL be unique so slugs identify a role within its Game
- **AND** a Game MAY define zero or more roles, and defining none SHALL leave every existing behavior unchanged

#### Scenario: Roles belong to the template and clone with it

- **WHEN** a Game (template) is cloned (see the `game-authoring-roles` capability)
- **THEN** the clone SHALL receive its own copies of the original's `GameRole`s
- **AND** any challenge role requirements copied into the clone SHALL reference the clone's roles, not the original's

### Requirement: Optional built-in role powers

The system SHALL let a `GameRole` optionally carry a known built-in power via a `builtin_power` flag, while roles without a power remain purely arbitrary game-defined roles.

#### Scenario: Role with no built-in power

- **WHEN** a creator defines a role without selecting a built-in power
- **THEN** the role's `builtin_power` SHALL default to `NONE`
- **AND** the role SHALL still be assignable to members and usable as a rule requirement, carrying no engine behavior of its own

#### Scenario: INVITER built-in power

- **WHEN** a role's `builtin_power` is `INVITER`
- **THEN** a member whose active `TeamMembership` holds that role SHALL be permitted to create invites for their own team (see the `team-invites` and `team-formation` capabilities)
- **AND** this permission SHALL extend, not replace, the existing staff-only invite path, so with no `INVITER` role assigned invite creation remains staff-only

### Requirement: Role assignment to team members

The system SHALL model role assignment as `organize.TeamRole` attaching a `GameRole` to a specific `TeamMembership`, so a member of a specific team in a specific run holds zero or more of that Game's roles.

#### Scenario: Assigning a role to a member

- **WHEN** a staff/runner assigns a role to a member's `TeamMembership`
- **THEN** the system SHALL create a `TeamRole` linking that membership to the `GameRole`, recording `assigned_by` and `assigned_at`
- **AND** the pair `(membership, role)` SHALL be unique so a member cannot hold the same role twice
- **AND** a role MAY be held by several members and a member MAY hold several roles

#### Scenario: Role must belong to the member's Game

- **WHEN** a role assignment would attach a `GameRole` whose Game differs from the membership's Game
- **THEN** the system SHALL reject the assignment
- **AND** the assignment surface SHALL only offer roles defined on the membership's Game

### Requirement: Roles usable as challenge requirements

The system SHALL let the rule mechanism require roles on a Challenge through a `role_requirement_mode` and a set of `required_roles`, so a challenge can require a specific role present or one-of-each of several roles.

#### Scenario: Requirement modes

- **WHEN** a creator sets a challenge's `role_requirement_mode`
- **THEN** `NONE` SHALL mean no role requirement (the default)
- **AND** `ANY` SHALL be satisfied when the submitting team's active role holders cover at least one of `required_roles` (a singleton set expresses "this specific role present")
- **AND** `ALL` SHALL be satisfied only when they cover every role in `required_roles` (one-of-each of several roles)
- **AND** a non-`NONE` mode SHALL require a non-empty `required_roles`, all belonging to the challenge's Game

#### Scenario: Requirement is independent of head-count

- **WHEN** the system evaluates a challenge's role requirement for a team
- **THEN** it SHALL count the distinct roles covered by the team's active role holders, never the number of members present
- **AND** a single member holding two required roles SHALL by themselves satisfy an `ALL` requirement over exactly those two roles
- **AND** a team of many members holding none of the required roles SHALL NOT satisfy the requirement

#### Scenario: Optional holder-presence hook

- **WHEN** a challenge sets `require_holders_present` to `True`
- **THEN** the requirement SHALL additionally demand that the required role's holder be present, deferring the presence test to the `presence-rules` capability
- **AND** when `require_holders_present` is `False` (the default) role assignment alone SHALL suffice, with no presence test

### Requirement: Role management API

The system SHALL expose role definitions and assignments over a staff/creator REST API, and surface role information to players.

#### Scenario: Managing role definitions

- **WHEN** a creator calls `GET/POST/PATCH/DELETE /api/staff/game_roles/` for a Game they may author
- **THEN** the system SHALL let them list, create, edit, and delete that Game's roles, including each role's `builtin_power`
- **AND** dedicated actions SHALL assign and unassign roles on a team member's membership

#### Scenario: Surfacing roles to players

- **WHEN** a player views a challenge that declares a role requirement
- **THEN** the system SHALL report the required roles and the mode, plus whether the player's current team satisfies the requirement
- **AND** the player SHALL be able to see which roles their own membership holds
