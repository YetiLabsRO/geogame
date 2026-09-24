## ADDED Requirements

### Requirement: Exporting and importing content from the staff app

The system SHALL let a staff user move content between installs without leaving the staff app.

#### Scenario: Exporting

- **WHEN** a staff user opens the bundles page
- **THEN** it SHALL list the Games and Collections available to export
- **AND** selecting any of them and exporting SHALL download one bundle file containing the selection

#### Scenario: Seeing what a bundle holds before importing it

- **WHEN** a staff user chooses a bundle file to import
- **THEN** the app SHALL show what the bundle contains, which of its content this install already has, and which names would collide — before offering to import
- **AND** it SHALL require the user to choose whether the import updates the existing content or lands an independent copy

#### Scenario: After an import

- **WHEN** an import finishes
- **THEN** the app SHALL report what was created, what was updated, and anything that was skipped and why
