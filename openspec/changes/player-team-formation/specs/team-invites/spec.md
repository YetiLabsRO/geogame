## MODIFIED Requirements

### Requirement: Staff-created invites

The system SHALL let staff — and, when the Game enables player-driven team formation, a team's captain or an authorised inviter — create single-use invites to a team, optionally targeted at a recipient email, with an expiration; and it SHALL support two invite kinds: an untied `QR` join code that any holder MAY accept while valid, and a recipient-bound `LINK` that only its named recipient MAY accept.

#### Scenario: Creating an invite

- **WHEN** a staff user — or, where player-driven team formation is enabled for the current Session, a team captain or inviter — calls `POST /api/invites/` with a team, an optional recipient email, an invite `kind`, and an expiration
- **THEN** the system SHALL generate a single-use, cryptographically random token
- **AND** if a recipient email is provided the system SHALL send an invite email containing `https://host/invite/{token}`
- **AND** a QR code image of the invite URL SHALL be available in the app for in-person invites

#### Scenario: Untied QR versus recipient-bound link

- **WHEN** an invite is created with `kind` `QR`
- **THEN** the token SHALL NOT be bound to any user, so any holder MAY accept it while it is valid (a shareable, forwardable code)
- **AND WHEN** an invite is created with `kind` `LINK` and a recipient email
- **THEN** the token SHALL be bound to that recipient so it cannot be forwarded to and redeemed by a different account (enforced at acceptance)

#### Scenario: Team creation is gated by a per-game toggle

- **WHEN** a non-staff user attempts to create a team
- **THEN** the system SHALL deny it UNLESS the current Session's effective `allow_player_team_creation` setting is enabled (see the `team-formation` capability), in which case a player MAY create a team
- **AND** staff and administrators SHALL be able to create teams regardless of the toggle

### Requirement: Invite preview and acceptance

The system SHALL let an invitee preview an invite and accept it to join the team, enforcing recipient binding for `LINK` invites and — when the team requires confirmation — routing acceptance through a pending join request instead of immediate membership.

#### Scenario: Previewing an invite

- **WHEN** anyone requests `GET /api/invites/{token}/` (unauthenticated)
- **THEN** the system SHALL return the invited team's name, TeamGroup name, expiration, and invite `kind` for preview rendering
- **AND** for a recipient-bound `LINK` invite it SHALL indicate that acceptance is restricted to the named recipient

#### Scenario: Accepting an untied QR invite

- **WHEN** an invitee calls `POST /api/invites/accept/{token}/` for a `QR` invite with either a logged-in session or signup fields (email, password, first/last name)
- **THEN** the system SHALL, when the team's effective confirmation policy is `AUTO_APPROVE`, create a `TeamMembership` linking the user to the team, mark the invite accepted (`accepted_by`, `accepted_at`), and return an auth token
- **AND** when the team requires confirmation the system SHALL instead create a `pending` join request (see the `team-formation` capability) and defer the membership

#### Scenario: Accepting a recipient-bound link

- **WHEN** an invitee accepts a `LINK` invite
- **THEN** the system SHALL require the accepting (or freshly registered) account's email to match the invite's bound recipient
- **AND** it SHALL reject a mismatched account with `403`, so a forwarded link cannot be redeemed by someone else

#### Scenario: Single-use and expiry

- **WHEN** an invitee attempts to accept an invite that has already been accepted or has expired
- **THEN** the system SHALL return `410 Gone` with a clear error

### Requirement: Invite management

The system SHALL let staff, and a team's captain for their own team when player-driven team formation is enabled, list, revoke, and resend invites.

#### Scenario: Managing invites

- **WHEN** a staff user calls `GET /api/invites/` — or a team captain calls it for their own team where player-driven team formation is enabled
- **THEN** the system SHALL list the invites they may manage, filterable by status (pending, accepted, expired, revoked)
- **AND** `DELETE /api/invites/{id}/` SHALL revoke a pending invite (subsequent accepts return `410 Gone`)
- **AND** `POST /api/invites/{id}/resend/` SHALL re-send the invite email without rotating the token
