## MODIFIED Requirements

### Requirement: Per-game rule configuration

The system SHALL let each Game configure gameplay rules so different events can behave differently, read from the current Session's Game rather than hardcoded, with selected knobs overridable per Session or per object.

#### Scenario: Configurable rule fields

- **WHEN** gameplay reads a rule threshold
- **THEN** it SHALL read `proximity_meters` (default 50), `cooloff_minutes` (default 5), and `initial_bonus_default` (default 0) from the current Session's Game config
- **AND** migrated games SHALL retain the historical 50-meter and 5-minute values as defaults

#### Scenario: Zone conquest rule default

- **WHEN** a Game is created
- **THEN** it SHALL carry a `zone_conquest_rule` with choices `ALL`, `MAJORITY`, or `ANY`, defaulting to `MAJORITY`
- **AND** this SHALL be the Game-wide default conquest rule, overridable per Session and per Zone (see the `scoring` and `geographic-map` capabilities)
- **AND** the `MAJORITY` default SHALL preserve the historical strict-majority behavior for existing games

#### Scenario: Scoring time-unit default

- **WHEN** a Game is created
- **THEN** it SHALL carry a `score_time_unit` with choices `SECOND`, `MINUTE`, or `HOUR`, defaulting to `MINUTE`
- **AND** this SHALL be the Game-wide default time unit used to accrue zone floating scores, overridable per Session (see the `scoring` capability)
- **AND** the `MINUTE` default SHALL leave existing score formulas unchanged

#### Scenario: Per-tower proximity override

- **WHEN** a tower defines its own `proximity_meters`
- **THEN** that tower's capture proximity SHALL use the tower value instead of the Game's game-wide `proximity_meters` default (see the `geographic-map` capability)

#### Scenario: Per-session rule overrides

- **WHEN** a Session sets a non-null `zone_conquest_rule` or `score_time_unit` override
- **THEN** the effective value for that Session SHALL be the Session override, otherwise the Game default

## ADDED Requirements

### Requirement: Rule configuration API

The system SHALL expose the conquest-rule and scoring time-unit knobs over the staff REST API on both the Game (defaults) and the Session (overrides).

#### Scenario: Editing Game defaults

- **WHEN** a staff user calls `POST /api/staff/games/` or `PATCH /api/staff/games/{id}/`
- **THEN** the system SHALL accept `zone_conquest_rule` and `score_time_unit` and validate them against their choices
- **AND** an invalid choice SHALL be rejected with a validation error

#### Scenario: Editing Session overrides

- **WHEN** a staff user calls `PATCH /api/staff/sessions/{id}/`
- **THEN** the system SHALL accept nullable `zone_conquest_rule` and `score_time_unit` overrides
- **AND** clearing an override to null SHALL make the Session inherit the Game default
