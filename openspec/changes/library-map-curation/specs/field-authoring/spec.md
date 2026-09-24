## ADDED Requirements

### Requirement: The field map shows what the library already holds

The system SHALL show a field curator the target Collection's existing elements on the field map.

#### Scenario: Standing near existing work

- **WHEN** a curator has a target Collection selected in field mode
- **THEN** the field map SHALL draw that Collection's existing towers and zones in place
- **AND** they SHALL be visually distinct from the element currently being captured
- **AND** a curator SHALL therefore be able to see that a place is already recorded before recording it again

#### Scenario: Opening an existing element

- **WHEN** a curator selects an existing element on the field map
- **THEN** the system SHALL let them attach media to it, attach a challenge to it, or correct its position
- **AND** these SHALL be the same operations available when the element was first captured

## MODIFIED Requirements

### Requirement: Drop a tower at the current GPS position

The system SHALL let a curator create a Tower at their current device position in one action, showing the reading's accuracy, and SHALL let them correct the position before saving.

#### Scenario: Dropping a tower

- **WHEN** a curator drops a tower in field mode
- **THEN** the system SHALL place it at the current geolocation fix
- **AND** it SHALL show the fix's accuracy
- **AND** it SHALL record that accuracy as capture provenance

#### Scenario: Correcting the position

- **WHEN** a curator adjusts where the tower will be placed
- **THEN** the system SHALL offer an adjustment usable one-handed on a phone, not only a small draggable marker
- **AND** it SHALL show how far the chosen point now lies from the device's own fix
- **AND** it SHALL offer returning the point to that fix

#### Scenario: A poor fix

- **WHEN** the fix's accuracy is worse than a documented threshold
- **THEN** the system SHALL say so
- **AND** it SHALL offer averaging further readings as well as manual correction
