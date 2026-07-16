# Game Configuration Specification

## Purpose

Define the `Game` as the reusable event configuration — the map, the rules, the challenge bank, and the team-group taxonomy — that can be re-run across multiple Sessions without re-creating map data.

## Requirements

### Requirement: Game owns the event configuration

The system SHALL model `organize.Game` as the reusable configuration for an event, owning its zones, towers, team groups, and challenges but not the running scoreboard.

#### Scenario: Game fields

- **WHEN** a Game is created
- **THEN** it SHALL have `slug` (URL-safe, unique), `name`, `base_point` and `base_zoom_level` (map defaults), `is_active`, `created_by`, and `created_at`
- **AND** it SHALL NOT carry a per-run clock; `start_time` and `end_time` live on the Session (see the `sessions` capability)

#### Scenario: Configuration is shared across sessions

- **WHEN** multiple Sessions run on the same Game
- **THEN** they SHALL share the Game's `Zone`, `Tower`, `Challenge`, and `TeamGroup` data while keeping separate scoreboards

### Requirement: Per-game rule configuration

The system SHALL let each Game configure gameplay rules so different events can behave differently, read from the current Session's Game rather than hardcoded.

#### Scenario: Configurable rule fields

- **WHEN** gameplay reads a rule threshold
- **THEN** it SHALL read `proximity_meters` (default 50), `cooloff_minutes` (default 5), and `initial_bonus_default` (default 0) from the current Session's Game config
- **AND** migrated games SHALL retain the historical 50-meter and 5-minute values as defaults

### Requirement: Games CRUD API

The system SHALL let staff manage Games over a REST API.

#### Scenario: Creating and editing a game

- **WHEN** a staff user calls `POST /api/staff/games/` or `PATCH /api/staff/games/{id}/`
- **THEN** the system SHALL create or edit the Game's name, slug, rules, and active flag

#### Scenario: Deactivating a game

- **WHEN** a Game is deactivated
- **THEN** it SHALL be hidden from the "create new session" picker
- **AND** running Sessions on that Game SHALL NOT be affected
