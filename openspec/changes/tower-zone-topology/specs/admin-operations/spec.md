## MODIFIED Requirements

### Requirement: Zone and Tower admin

The system SHALL provide admin screens for zones and towers with ownership visibility, many-to-many zone membership management, and management actions.

#### Scenario: Zone admin

- **WHEN** a staff member opens the Zone admin
- **THEN** the list SHALL be color-coded and show the current per-TeamGroup controller
- **AND** it SHALL show the zone's member towers (or their count) via the many-to-many membership

#### Scenario: Zone admin enforces the at-least-one-tower invariant

- **WHEN** a staff member edits or deletes a zone in a way that would leave it with zero member towers
- **THEN** the admin SHALL block the save or delete with a validation error (see the `geographic-map` capability)

#### Scenario: Tower admin

- **WHEN** a staff member opens the Tower admin
- **THEN** the list SHALL be filterable by `zones` (the many-to-many membership), active, and category (NORMAL vs RFID)
- **AND** it SHALL show the current owner per TeamGroup and expose `initial_bonus`, `decrease_initial_bonus`, `rfid_code`, and a public RFID URL
- **AND** a tower's `zones` SHALL be editable as a multi-select many-to-many field rather than a single-zone picker

#### Scenario: Autocreate circle zone adds to the tower's zones

- **WHEN** a tower is saved with `autocreate_zone` set and it currently has no zones
- **THEN** the admin SHALL create a circular zone and add it to the tower's `zones` set (rather than setting a single `zone` foreign key)
- **AND** the tower SHALL become that new zone's founding member, satisfying the at-least-one-tower invariant
