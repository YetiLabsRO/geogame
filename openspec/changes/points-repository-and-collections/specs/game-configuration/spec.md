## MODIFIED Requirements

### Requirement: Game owns the event configuration

The system SHALL model `organize.Game` as the reusable creator-authored **template** for an event, owning its rules, challenge bank, and team-group taxonomy, and referencing its map through Collections rather than owning geometry directly.

#### Scenario: Game fields

- **WHEN** a Game is created
- **THEN** it SHALL have `slug` (URL-safe, unique), `name`, `base_point` and `base_zoom_level` (map defaults), `is_active`, `created_by`, and `created_at`
- **AND** it SHALL reference its map through a many-to-many `collections` relation to `game.Collection` (see the `collections` capability), instead of owning `Zone` and `Tower` rows via a `game` foreign key
- **AND** it SHALL NOT carry a per-run clock; `start_time` and `end_time` live on the Session (see the `sessions` capability)

#### Scenario: Configuration is shared across sessions

- **WHEN** multiple Sessions run on the same Game
- **THEN** they SHALL share the Game's linked `Collection`s (and therefore its `Zone`s and `Tower`s), its `Challenge` bank, and its `TeamGroup` taxonomy, while keeping separate scoreboards

#### Scenario: Many games on one map

- **WHEN** two or more Games link the same Collection
- **THEN** they SHALL share the same underlying `Tower` and `Zone` rows
- **AND** each Game's Sessions SHALL keep independent ownership records so gameplay never leaks between Games
