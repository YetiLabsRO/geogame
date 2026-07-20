## ADDED Requirements

### Requirement: Per-game player team-formation toggle

The system SHALL gate player-driven team creation behind a per-Game `allow_player_team_creation` setting that defaults to `False`, with a nullable per-Session override resolved so the Session override wins when set, otherwise the Game default applies.

#### Scenario: Default preserves staff-only creation

- **WHEN** a Game is created without configuring the toggle
- **THEN** `allow_player_team_creation` SHALL default to `False`
- **AND** non-staff users SHALL NOT be able to create teams, preserving today's staff-only behaviour (see the `team-invites` capability)

#### Scenario: Per-session override wins

- **WHEN** a Session sets `allow_player_team_creation` to a non-null value
- **THEN** the effective setting for that Session SHALL be the Session value
- **AND** when the Session value is null the effective setting SHALL fall back to the Game default

#### Scenario: Administrators can always create teams

- **WHEN** a staff user or administrator creates a team
- **THEN** the system SHALL permit it regardless of the effective `allow_player_team_creation` value

### Requirement: Player-created teams

The system SHALL let an authenticated player create a team in their current Session when the effective `allow_player_team_creation` is enabled, making the creator the team captain and first member.

#### Scenario: Creating a team as a player

- **WHEN** a player calls `POST /api/teams/` with a name and an optional TeamGroup while the effective toggle is enabled for their current Session
- **THEN** the system SHALL create the team in that Session, record the creator as its **captain**, and add the creator as its first `TeamMembership`
- **AND** the team MAY belong to one TeamGroup within the Session's Game (see the `teams-and-groups` capability)

#### Scenario: Denied when the toggle is off

- **WHEN** a non-staff player calls `POST /api/teams/` while the effective toggle is disabled
- **THEN** the system SHALL deny it with `403`

#### Scenario: One active membership per game still holds

- **WHEN** creating a team would give the player a second active `TeamMembership` within the same Game
- **THEN** the system SHALL reject it with a clear error (see the `sessions` capability)

### Requirement: Team captain

The system SHALL treat the creating player as the team captain, who MAY invite people, rotate or revoke the team's join code, and approve or reject join requests for that team.

#### Scenario: Creator becomes captain

- **WHEN** a player creates a team
- **THEN** the system SHALL record them as the captain
- **AND** the captain SHALL be authorised to manage that team's invites and join requests, while staff MAY manage any team's

### Requirement: Shareable untied team join code

The system SHALL let a captain (or staff) generate a shareable, untied join code / QR for their team that any holder MAY use while it is valid, and that MAY be rotated or revoked.

#### Scenario: Generating a shareable join QR

- **WHEN** a captain requests their team's join code
- **THEN** the system SHALL expose an untied token rendered as a QR image and a copyable join link
- **AND** the token SHALL NOT be bound to any specific user, so it MAY be forwarded to a friend group (contrast the recipient-bound invitation link in the `team-invites` capability)

#### Scenario: Rotating or revoking the join code

- **WHEN** a captain calls `POST /api/teams/{id}/join-code/` to rotate or revoke the code
- **THEN** the system SHALL issue a new token (rotate) or invalidate the current one (revoke)
- **AND** subsequent uses of a revoked or superseded code SHALL be rejected

### Requirement: Browse teams and request to join

The system SHALL let a player browse the joinable teams in their current Session and submit a request to join one.

#### Scenario: Browsing joinable teams

- **WHEN** a player calls `GET /api/joinable-teams/`
- **THEN** the system SHALL return the teams in the player's current Session that they may request to join

#### Scenario: Requesting to join a browsed team

- **WHEN** a player calls `POST /api/join-requests/` for a team while holding no active membership in that Game
- **THEN** the system SHALL create a `TeamJoinRequest` with `source` `BROWSE`
- **AND** its initial status SHALL be `pending` unless the team's effective confirmation policy is `AUTO_APPROVE`, in which case the membership SHALL be created immediately

### Requirement: Join requests track pending, approved, and rejected states

The system SHALL model `organize.TeamJoinRequest` with a `status` of `pending`, `approved`, or `rejected`, recording who decided it and when.

#### Scenario: Join-request fields

- **WHEN** a `TeamJoinRequest` is created
- **THEN** it SHALL carry a `team`, a requesting `user`, a `status` (default `pending`), a `source` (`BROWSE`, `QR`, or `LINK`), and a `requested_at` timestamp
- **AND** on decision it SHALL record `decided_by` and `decided_at`

#### Scenario: Approving a request creates a membership

- **WHEN** the team captain or a staff user calls `POST /api/join-requests/{id}/approve/`
- **THEN** the system SHALL set the request status to `approved`, stamp `decided_by`/`decided_at`, and create the `TeamMembership`
- **AND** it SHALL surface a clear error if that membership would violate the one-active-membership-per-game constraint (see the `sessions` capability)

#### Scenario: Rejecting a request

- **WHEN** the team captain or a staff user calls `POST /api/join-requests/{id}/reject/`
- **THEN** the system SHALL set the request status to `rejected`, stamp `decided_by`/`decided_at`, and SHALL NOT create a membership

#### Scenario: Request visibility

- **WHEN** a client calls `GET /api/join-requests/`
- **THEN** a captain SHALL see their own team's requests, staff SHALL see requests for teams they manage, and a player SHALL see their own requests
- **AND** the list SHALL be filterable by status

### Requirement: Confirmation policy

The system SHALL resolve a team's join-confirmation policy from a per-Game `team_join_confirmation` default with a nullable per-Team override, and route joins accordingly: `AUTO_APPROVE` grants membership immediately, while `CAPTAIN` or `STAFF` require approval by an authorised user.

#### Scenario: Auto-approve grants membership immediately

- **WHEN** a join request or an untied QR join targets a team whose effective confirmation policy is `AUTO_APPROVE`
- **THEN** the system SHALL create the `TeamMembership` without a pending step

#### Scenario: Confirmation required leaves a pending request

- **WHEN** a join request or an untied QR join targets a team whose effective confirmation policy is `CAPTAIN` or `STAFF`
- **THEN** the system SHALL create (or keep) a `pending` `TeamJoinRequest` and SHALL NOT create the membership until an authorised user approves it

#### Scenario: Per-team override wins

- **WHEN** a Team sets a non-null `team_join_confirmation`
- **THEN** the effective policy for that team SHALL be the Team value, otherwise it SHALL fall back to the Game default

### Requirement: Accepting a secret invite or QR to join

The system SHALL let a player accept a secret invite or scan a team QR to join, resolving to immediate membership or a pending request per the team's confirmation policy, and recording the request source.

#### Scenario: Untied QR join under auto-approve

- **WHEN** a player uses an untied team QR / join code for a team whose effective confirmation policy is `AUTO_APPROVE`
- **THEN** the system SHALL create the `TeamMembership` immediately
- **AND** any resulting request record SHALL carry `source` `QR`

#### Scenario: Untied QR join requiring confirmation

- **WHEN** a player uses an untied team QR / join code for a team whose effective confirmation policy is `CAPTAIN` or `STAFF`
- **THEN** the system SHALL create a `pending` `TeamJoinRequest` with `source` `QR` and defer membership until it is approved

#### Scenario: Recipient-bound link join

- **WHEN** a player accepts a recipient-bound invitation link (see the `team-invites` capability)
- **THEN** the system SHALL honour the recipient binding and, on success, either create the membership or a `pending` `TeamJoinRequest` with `source` `LINK` per the confirmation policy

### Requirement: Team-formation API

The system SHALL expose the player team-formation flows over a REST API authenticated with DRF Token authentication.

#### Scenario: Endpoints

- **WHEN** an authenticated player uses the module
- **THEN** the system SHALL provide `POST /api/teams/` (create), `POST /api/teams/{id}/join-code/` (rotate/revoke), `GET /api/joinable-teams/`, `POST /api/join-requests/`, `GET /api/join-requests/`, `POST /api/join-requests/{id}/approve/`, and `POST /api/join-requests/{id}/reject/`
- **AND** every endpoint SHALL enforce that the caller acts only within their current Session and only on teams they are authorised for

### Requirement: Player team-formation UI

The system SHALL provide player-app UI, built as Angular standalone components using signals and `OnPush` change detection, for creating a team, sharing its QR/link, browsing and requesting to join, and (for captains) approving pending requests.

#### Scenario: Player module rendering

- **WHEN** the effective `allow_player_team_creation` is enabled for the player's current Session
- **THEN** the player app SHALL show a create-team screen, a share screen with the team QR image and a copyable join link, and a browse-and-request screen
- **AND** a captain SHALL additionally see a list of pending join requests with approve and reject actions

### Requirement: Admin shuffle and balanced team building

The system SHALL provide staff an optional facility to auto-assign unassigned players into teams, either by random shuffle into a chosen number of teams or by a balanced build that distributes players across teams using arbitrary key-value profile attributes; the result is best-effort and editable before the Session starts.

#### Scenario: Random shuffle

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/shuffle-teams/` with a target team count
- **THEN** the system SHALL distribute the Session's unassigned players randomly into that many teams
- **AND** the result SHALL remain editable before the Session starts

#### Scenario: Balanced build from profile attributes

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/balance-teams/` with a target team count and one or more profile attribute keys
- **THEN** the system SHALL bucket unassigned players by those key-value attributes and distribute them round-robin so the buckets are spread as evenly as the inputs allow across the teams
