# Player App Specification

## Purpose

Deliver the player-facing game experience as an Angular v21 SPA (`frontend/projects/player`) that consumes the DRF API — replacing the removed Django templates for all player routes.

## Requirements

### Requirement: Player SPA scope

The system SHALL provide an Angular player app covering all player-facing functionality.

#### Scenario: Player routes

- **WHEN** a player uses the app
- **THEN** it SHALL provide auth screens (login, register, password reset, invite-accept), the main map, per-TeamGroup score maps at `/map/<team_group_slug>/`, tower detail, challenge submission, RFID capture, and a rules page
- **AND** it SHALL be built with standalone components, signals, `@if`/`@for` control flow, `input()`/`output()`/`inject()`, and `ChangeDetectionStrategy.OnPush`
- **AND** it SHALL consume the DRF API; Django templates for these routes have been removed

### Requirement: Live map rendering

The system SHALL render a live Leaflet map of zones and active towers colored by current TeamGroup control.

#### Scenario: Viewing the map

- **WHEN** a player opens the main map
- **THEN** it SHALL render zones and active towers via Leaflet, colored by current per-TeamGroup ownership
- **AND** it SHALL update via polling or a refresh action (no websockets required)

### Requirement: GPS proximity feedback

The system SHALL give the player live proximity feedback before they submit.

#### Scenario: Submitting near vs far

- **WHEN** a player is on the tower detail page
- **THEN** it SHALL show live distance-to-tower from device GPS
- **AND** it SHALL disable the submit button when the player is farther than the Session's `proximity_meters` from the tower
- **AND** photo upload SHALL use the browser camera via `<input type="file" capture="environment">`

### Requirement: Cooldown feedback

The system SHALL show the player when they can retry after a rejection.

#### Scenario: After a rejected attempt

- **WHEN** a player's most recent attempt on a tower was rejected and the cooldown is active
- **THEN** the tower page SHALL show a countdown until the cooldown expires

### Requirement: Default-session selection in the app

The system SHALL route a player to their run automatically when unambiguous.

#### Scenario: Choosing a session

- **WHEN** a player logs in with exactly one active membership on an active Session
- **THEN** the app SHALL auto-select that Session; otherwise it SHALL present a session picker
