## ADDED Requirements

### Requirement: Typing a tower in the field is one action

The system SHALL let a field curator apply a tower type while capturing, without opening a form.

#### Scenario: Dropping a typed tower

- **WHEN** a curator captures a tower in field mode
- **THEN** the mode SHALL offer the available tower types as directly selectable controls
- **AND** selecting one SHALL apply that type's icon, colour and default capture radius to the tower being captured
- **AND** the curator SHALL still be able to save a tower with no type

#### Scenario: Seeing what a type implies

- **WHEN** a type is selected during capture
- **THEN** the capture panel SHALL show the capture radius that will apply
- **AND** where that radius is smaller than the current GPS accuracy, the mode SHALL say so, because a tower placed less precisely than its own capture radius cannot reliably be captured
