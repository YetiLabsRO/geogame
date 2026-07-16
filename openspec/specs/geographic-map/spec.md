# Geographic Map Specification

## Purpose

Define the geospatial data model — Zones (polygons) and Towers (points) — that make up an event's map, and expose them (with current per-TeamGroup ownership coloring) so player and staff clients can render a live map.

## Requirements

### Requirement: Zone definition

The system SHALL model a `game.Zone` as a geographic polygon that groups towers and awards area-wide points to the team controlling it.

#### Scenario: Creating a zone

- **WHEN** an administrator creates a zone
- **THEN** the system SHALL store a `PolygonField` boundary, a human-readable name, a display color, and a `score_type` strategy
- **AND** the `score_type` SHALL be one of `LINEAR`, `LOGARITHMIC`, `EXPONENTIAL`, or `BONUS` (the per-strategy scoring formulas are defined by the `scoring` capability)

#### Scenario: Zone belongs to a game

- **WHEN** a zone is created
- **THEN** it SHALL carry a mandatory `game` foreign key so map data is reusable across every Session of that Game

### Requirement: Tower definition

The system SHALL model a `game.Tower` as a geographic point that teams capture as a physical objective.

#### Scenario: Creating a tower

- **WHEN** an administrator creates a tower
- **THEN** the system SHALL store its location as a `PointField`, a name, a mandatory `game` foreign key, and optionally an owning `zone`
- **AND** the tower SHALL carry a `category` of `NORMAL` (GPS-verified capture) or `RFID` (tag-scanned capture)
- **AND** the tower SHALL carry an `is_active` flag and an `initial_bonus` integer

#### Scenario: RFID tower requires a code

- **WHEN** a tower's category is `RFID`
- **THEN** the tower SHALL have a unique `rfid_code` used for tag-based capture (see the `rfid-capture` capability)

#### Scenario: Deactivating a tower releases ownership

- **WHEN** a tower's `is_active` flag is set to `False`
- **THEN** the system SHALL close all of the tower's current team and zone ownerships and recompute zone control (see the `game-lifecycle` capability)

### Requirement: Live map data with ownership coloring

The system SHALL expose zones and active towers over a REST API so clients can render a live map colored by current control.

#### Scenario: Fetching zones

- **WHEN** a client requests `GET /api/zones/`
- **THEN** the system SHALL return zones as GeoJSON (via `rest_framework_gis`) with current per-TeamGroup ownership coloring
- **AND** an optional `group` query parameter SHALL color the zones by the named TeamGroup

#### Scenario: Fetching towers with proximity filtering

- **WHEN** a client requests `GET /api/towers/`
- **THEN** the system SHALL return only active towers as GeoJSON
- **AND** it SHALL accept optional `lat`, `lng`, and `accuracy` query parameters for proximity filtering
