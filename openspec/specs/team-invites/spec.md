# Team Invites Specification

## Purpose

Let staff build team rosters by inviting scouts via email or QR code, with single-use tokens that invitees accept to join a team — registering a new account or using an existing one.

## Requirements

### Requirement: Staff-created invites

The system SHALL let staff create single-use invites to a team, optionally by email, with an expiration.

#### Scenario: Creating an invite

- **WHEN** a staff user calls `POST /api/invites/` with a team, an optional email, and an expiration
- **THEN** the system SHALL generate a single-use, cryptographically random token
- **AND** if an email is provided, the system SHALL send an invite email containing `https://host/invite/{token}`
- **AND** a QR code image of the invite URL SHALL be available in the staff UI for in-person invites

#### Scenario: Team creation is staff-only

- **WHEN** a non-staff user attempts to create a team
- **THEN** the system SHALL deny it; team creation SHALL be restricted to staff

### Requirement: Invite preview and acceptance

The system SHALL let an invitee preview an invite and accept it to join the team.

#### Scenario: Previewing an invite

- **WHEN** anyone requests `GET /api/invites/{token}/` (unauthenticated)
- **THEN** the system SHALL return the invited team's name, TeamGroup name, and expiration for preview rendering

#### Scenario: Accepting an invite

- **WHEN** an invitee calls `POST /api/invites/accept/{token}/` with either a logged-in session or signup fields (email, password, first/last name)
- **THEN** the system SHALL create a `TeamMembership` linking the user to the invited team, mark the invite accepted (`accepted_by`, `accepted_at`), and return an auth token
- **AND** subsequent accept attempts SHALL return `410 Gone`

#### Scenario: Expired invite

- **WHEN** an invitee attempts to accept an expired invite
- **THEN** the system SHALL return `410 Gone` with a clear error

### Requirement: Invite management

The system SHALL let staff list, revoke, and resend invites.

#### Scenario: Managing invites

- **WHEN** a staff user calls `GET /api/invites/`
- **THEN** the system SHALL list invites for teams they can manage, filterable by status (pending, accepted, expired, revoked)
- **AND** `DELETE /api/invites/{id}/` SHALL revoke a pending invite (subsequent accepts return `410 Gone`)
- **AND** `POST /api/invites/{id}/resend/` SHALL re-send the invite email without rotating the token
