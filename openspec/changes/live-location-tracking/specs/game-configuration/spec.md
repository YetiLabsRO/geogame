## MODIFIED Requirements

### Requirement: Per-game rule configuration

The system SHALL let each Game configure gameplay rules so different events can behave differently, read from the current Session's Game rather than hardcoded, and resolved through an effective-value helper where a nullable per-Session override wins over the Game default.

#### Scenario: Configurable rule fields

- **WHEN** gameplay reads a rule threshold
- **THEN** it SHALL read `proximity_meters` (default 50), `cooloff_minutes` (default 5), and `initial_bonus_default` (default 0) from the current Session's Game config
- **AND** migrated games SHALL retain the historical 50-meter and 5-minute values as defaults

#### Scenario: Location knobs follow the same resolution

- **WHEN** gameplay or the player app reads a location setting
- **THEN** it SHALL resolve the location config fields the same way — a nullable per-Session override wins, else the Game default (see the `location tracking configuration` requirement and the `live-location` capability)

## ADDED Requirements

### Requirement: Location tracking configuration

The system SHALL let each Game configure live location tracking, defaulting to tracking off, with the update frequency, visibility, retention, and consent text as game-level settings and nullable per-Session overrides for the runner.

#### Scenario: Location config fields

- **WHEN** a Game is configured
- **THEN** it SHALL expose `location_tracking_enabled` (default `False`), `location_ping_interval_seconds` (default `30`), `location_visibility` (one of `NONE`, `OWN_TEAM`, `EVERYONE`, default `OWN_TEAM`), `location_retention_days` (default `30`), and `location_consent_text`
- **AND** each field SHALL have a nullable per-Session override resolved by the effective-value helper (Session override wins, else Game default)
- **AND** existing Games SHALL default to tracking off so current behavior is unchanged

#### Scenario: Update frequency is game-level only

- **WHEN** the update frequency is read for a Session
- **THEN** it SHALL come from the effective `location_ping_interval_seconds` (Session override or Game default)
- **AND** no per-player setting SHALL exist that changes it (see the `live-location` capability)

#### Scenario: Enabling tracking requires consent to play

- **WHEN** a Game has `location_tracking_enabled` true for a Session
- **THEN** playing that Session SHALL require a player to consent to the `location_consent_text` rules
- **AND** when tracking is false, no consent SHALL be required and no positions SHALL be collected
