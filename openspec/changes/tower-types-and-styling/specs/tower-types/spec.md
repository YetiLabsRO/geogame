## ADDED Requirements

### Requirement: Tower types

The system SHALL provide a managed set of tower types that carry a tower's visual identity and its configuration defaults, so a curator describes a kind of place once rather than on every tower.

#### Scenario: Defining a type

- **WHEN** a staff user creates a tower type
- **THEN** the system SHALL record a name, an icon, a colour, and optionally a default capture radius and a description
- **AND** the type SHALL be available to every tower in the repository, independent of any Game or Collection

#### Scenario: Applying a type

- **WHEN** a curator assigns a type to a tower
- **THEN** the tower SHALL take that type's icon and colour
- **AND** the tower SHALL take the type's default capture radius wherever it does not specify its own

#### Scenario: A tower with no type

- **WHEN** a tower has no type
- **THEN** the system SHALL render it with a documented neutral default icon and colour
- **AND** its capture radius SHALL resolve exactly as it did before types existed

#### Scenario: Retiring a type

- **WHEN** a type is deleted
- **THEN** the towers that carried it SHALL survive
- **AND** they SHALL fall back to the untyped defaults rather than becoming unreadable or unresolvable

### Requirement: Tower styling resolves tower over type over default

The system SHALL resolve a tower's icon and colour from the tower's own override first, then its type, then a documented default.

#### Scenario: Overriding one facet of a type

- **WHEN** a tower carries a type and sets its own colour but not its own icon
- **THEN** the resolved colour SHALL be the tower's
- **AND** the resolved icon SHALL be the type's
- **AND** the tower SHALL remain a member of that type

#### Scenario: Clearing an override

- **WHEN** a tower's own icon or colour override is cleared
- **THEN** the resolved value SHALL revert to the type's, or to the default when there is no type

### Requirement: Capture radius resolves through the type

The system SHALL resolve a tower's effective capture radius as the tower's own value, then its type's default, then the Game's default.

#### Scenario: A type supplying the radius

- **WHEN** a tower specifies no capture radius of its own and its type specifies one
- **THEN** capture proximity checks SHALL use the type's radius

#### Scenario: Every derivation agrees

- **WHEN** the effective radius is derived for the same tower by proximity checking, by nearby-tower filtering, and by presence geofencing
- **THEN** all of them SHALL produce the same value
- **AND** a tower SHALL NOT be able to appear in a nearby-tower list under one radius while refusing capture under another

### Requirement: Resolved styling is served, not recomputed

The system SHALL expose each tower's resolved icon and colour in its API representation.

#### Scenario: A client drawing towers

- **WHEN** a client renders towers on a map
- **THEN** it SHALL be able to read the resolved icon and colour directly from the tower's representation
- **AND** it SHALL NOT need to fetch types separately or re-implement the resolution order to draw correctly
