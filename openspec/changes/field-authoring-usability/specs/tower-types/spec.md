## ADDED Requirements

### Requirement: An install begins with a usable vocabulary

The system SHALL provide a starting set of Tower types, so a curator's first tower can be typed without their having to invent a taxonomy first.

#### Scenario: A new install

- **WHEN** the system is installed and no Tower types exist
- **THEN** it SHALL create a starting set covering the kinds of place a town is scouted for
- **AND** each SHALL carry an icon and a colour, so the set is usable as it stands

#### Scenario: An install that already has its own

- **WHEN** Tower types already exist
- **THEN** the system SHALL NOT add to or alter them
- **AND** a curator's own vocabulary SHALL never be overwritten by a starting set

#### Scenario: The set is a starting point, not a fixture

- **WHEN** a curator renames, restyles, removes or adds to the starting set
- **THEN** the system SHALL keep their changes
- **AND** removing a type SHALL leave its towers untyped rather than deleting them
