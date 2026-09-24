## ADDED Requirements

### Requirement: Sessions survive a page reload

The system SHALL keep a signed-in user signed in across a page reload, including a hard refresh and a direct visit to a deep link.

#### Scenario: Reloading a staff page

- **WHEN** a signed-in staff user reloads any staff page
- **THEN** the system SHALL keep them signed in and on that page
- **AND** it SHALL NOT redirect them to the login page

#### Scenario: Opening a deep link directly

- **WHEN** a signed-in user opens a deep link to a permitted page in a new tab or from a bookmark
- **THEN** the system SHALL admit them to that page without a further sign-in

### Requirement: Unresolved authorization state is not a denial

The system SHALL resolve the information an authorization decision depends on before deciding, and SHALL NOT treat "not loaded yet" as grounds for denial.

#### Scenario: Authorizing before the profile has loaded

- **WHEN** a route requires a property of the user's profile and the profile has not been loaded yet
- **THEN** the system SHALL wait for the profile and then decide
- **AND** a user who holds the required property SHALL be admitted

#### Scenario: One fetch per reload

- **WHEN** several parts of the app need the profile at the same time after a reload
- **THEN** the system SHALL issue a single request and share its result

### Requirement: A rejected token ends the session cleanly

The system SHALL discard a stored token the server no longer accepts, rather than retrying with it indefinitely.

#### Scenario: A stale stored token

- **WHEN** the stored token is rejected while resolving the user's profile
- **THEN** the system SHALL clear it and send the user to sign in
- **AND** it SHALL NOT loop between the guarded route and the login page

#### Scenario: Returning to the attempted page

- **WHEN** a user is sent to sign in from a page they attempted to open
- **THEN** signing in SHALL return them to that page
