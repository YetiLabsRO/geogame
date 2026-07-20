## MODIFIED Requirements

### Requirement: Player SPA scope

The system SHALL provide an Angular player app covering all player-facing functionality.

#### Scenario: Player routes

- **WHEN** a player uses the app
- **THEN** it SHALL provide auth screens (login, register, password reset, invite-accept), the main map, per-TeamGroup score maps at `/map/<team_group_slug>/`, tower detail, challenge submission, RFID capture, and a rules page
- **AND** for a location-enabled Session it SHALL provide a location-consent gate that presents the game's location rules and requires agreement before play (see the `live-location` capability)
- **AND** it SHALL be built with standalone components, signals, `@if`/`@for` control flow, `input()`/`output()`/`inject()`, and `ChangeDetectionStrategy.OnPush`
- **AND** it SHALL consume the DRF API; Django templates for these routes have been removed

### Requirement: Live map rendering

The system SHALL render a live Leaflet map of zones and active towers colored by current TeamGroup control.

#### Scenario: Viewing the map

- **WHEN** a player opens the main map
- **THEN** it SHALL render zones and active towers via Leaflet, colored by current per-TeamGroup ownership
- **AND** it SHALL update via polling or a refresh action (no websockets required)

#### Scenario: Live player positions overlay

- **WHEN** a player views the map in a location-enabled Session
- **THEN** it SHALL overlay the latest visible player/team positions from `GET /api/location/live/`, respecting the effective `location_visibility` (see the `live-location` capability)
- **AND** when `location_visibility` is `NONE` it SHALL show no other players' positions

## ADDED Requirements

### Requirement: Player location consent and streaming

The system SHALL let a consenting player stream their live location at the game-configured cadence and SHALL never expose a player-facing frequency control.

#### Scenario: Consent gate before streaming

- **WHEN** a player enters a location-enabled Session without standing consent
- **THEN** the app SHALL present the game's location rules and require the player to agree (recording consent via `POST /api/location/consent/`) before play
- **AND** the app SHALL let the player withdraw consent later, which stops streaming (see the `live-location` capability)

#### Scenario: Streaming at the game interval

- **WHEN** a consented player is playing a location-enabled Session
- **THEN** the app SHALL stream position pings to `POST /api/location/ping/` at the effective `location_ping_interval_seconds`
- **AND** it SHALL read that interval from the Session config and provide no control for the player to change it
- **AND** it SHALL pause streaming whenever consent is absent or tracking is disabled
