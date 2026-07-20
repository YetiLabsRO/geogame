## MODIFIED Requirements

### Requirement: KML import command

The system SHALL provide an `import_data` management command that seeds repository Zones and Towers from KML files and groups them into a target Collection.

#### Scenario: Importing map data

- **WHEN** an administrator runs `manage.py import_data`
- **THEN** the command SHALL parse `zone_normal.kml`, `zone_bonus.kml`, and `puncte.kml` to populate repository Zones and Towers
- **AND** it SHALL add the imported Zones and Towers to a named target `Collection` (created if absent) rather than assigning them a single-Game owner (see the `collections` capability)

#### Scenario: Idempotent by replacement

- **WHEN** the command is run again for the same target Collection
- **THEN** it SHALL delete and recreate the Zone and Tower data for that Collection (idempotent by replacement, not by merge)
