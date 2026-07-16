# User Accounts Specification

## Purpose

Provide per-person accounts (built on Django's `User` with a `UserProfile` extension) with token authentication, so submissions and team membership are tied to an individual rather than a shared code.

## Requirements

### Requirement: Per-person accounts

The system SHALL support per-person accounts built on Django's `User` model with a `UserProfile` 1:1 extension.

#### Scenario: Account lifecycle

- **WHEN** a person uses the system
- **THEN** they SHALL be able to register (email + password), log in, log out, and reset their password via email
- **AND** a user SHALL hold at most one active `TeamMembership` per `(user, game)` pair (see the `sessions` capability)

### Requirement: Token authentication

The system SHALL authenticate API requests using DRF Token authentication.

#### Scenario: Issuing and invalidating tokens

- **WHEN** a user logs in via `POST /api/auth/login`
- **THEN** the system SHALL issue a DRF auth token
- **AND** `POST /api/auth/logout` SHALL invalidate the token
- **AND** `POST /api/auth/register` and `POST /api/auth/password-reset` SHALL support account creation and password recovery

### Requirement: Me endpoint

The system SHALL expose the current user's personalized state.

#### Scenario: Fetching my state

- **WHEN** an authenticated user calls `GET /api/me/`
- **THEN** the system SHALL return their profile, active team membership, current Session selection, and permissions
- **AND** `PATCH /api/me/` SHALL update editable profile fields and `GET /api/my-team/` SHALL return their active team
