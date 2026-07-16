# Data Import Specification

## Purpose

Seed zones and towers from KML files exported from Google Earth, so map authoring stays outside the application.

## Requirements

### Requirement: KML import command

The system SHALL provide an `import_data` management command that seeds Zones and Towers from KML files.

#### Scenario: Importing map data

- **WHEN** an administrator runs `manage.py import_data`
- **THEN** the command SHALL parse `zone_normal.kml`, `zone_bonus.kml`, and `puncte.kml` to populate Zones and Towers

#### Scenario: Idempotent by replacement

- **WHEN** the command is run again
- **THEN** it SHALL delete and recreate the Zone and Tower data (idempotent by replacement, not by merge)
