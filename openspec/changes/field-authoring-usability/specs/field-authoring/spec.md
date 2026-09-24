## MODIFIED Requirements

### Requirement: Drop a tower at the current GPS position

The system SHALL let a curator create a Tower at a point they choose, offered at the device's current GPS position.

#### Scenario: Dropping a tower where the curator stands

- **WHEN** a curator begins a tower capture
- **THEN** the system SHALL offer the device's current geolocation as the point, shown as a single marker distinct from the indicator for the device's own position
- **AND** it SHALL display the reading's accuracy in metres and record it as capture provenance on the tower
- **AND** saving SHALL create a `game.Tower` whose `PointField` is the chosen point

#### Scenario: Choosing a different point

- **WHEN** a curator taps the map, or drags the marker
- **THEN** the system SHALL move the point being captured to that position
- **AND** it SHALL say how far the chosen point now lies from the device's own reading
- **AND** it SHALL offer a way to return the point to the device's position

#### Scenario: Asking the device again

- **WHEN** a curator asks for the position to be re-read
- **THEN** the system SHALL take a fresh reading and show its accuracy
- **AND** this SHALL be available whenever field mode is open, not only during a capture

#### Scenario: Poor accuracy warning

- **WHEN** the current GPS accuracy is worse than a configured threshold
- **THEN** the system SHALL warn the curator before saving
- **AND** it SHALL offer to average multiple readings or retry so the stored position is usable for capture

### Requirement: Add field elements to the target Collection

The system SHALL add Towers and Zones created or adjusted in field authoring mode to the session's active target Collection, and SHALL show the curator what that Collection already holds.

#### Scenario: New geometry joins the collection

- **WHEN** a curator saves a newly dropped Tower or drawn Zone in field authoring mode
- **THEN** the system SHALL add it to the active target Collection (see the `collections` capability) so it becomes part of that reusable map
- **AND** the curator SHALL be able to switch the target Collection for subsequently created elements

#### Scenario: Seeing what is already there

- **WHEN** a target Collection is active
- **THEN** the field map SHALL draw that Collection's existing Towers and Zones
- **AND** they SHALL be drawn so as not to be mistaken for the element being captured
- **AND** a curator SHALL NOT have to choose a Collection before the map can show them anything

#### Scenario: Starting a new map in the field

- **WHEN** a curator sets out to scout somewhere no Collection covers
- **THEN** the system SHALL let them create a Collection from field mode
- **AND** it SHALL become the active target for what they create next

#### Scenario: Staging drafts before publishing

- **WHEN** a curator wants to scout without exposing incomplete geometry to live games
- **THEN** the system SHALL allow field-created Towers to be saved as inactive drafts (reusing the Tower `is_active` flag)
- **AND** an inactive draft tower SHALL be excluded from live session scoping until the curator activates it

### Requirement: Draw and adjust zones on site

The system SHALL let a curator draw a new Zone polygon or adjust an existing one directly on the mobile map, as readily as they can drop a tower.

#### Scenario: Starting a zone

- **WHEN** a curator is deciding what to record
- **THEN** drawing a zone SHALL be offered as prominently as dropping a tower

#### Scenario: Walking the boundary

- **WHEN** a curator chooses to draw a zone by walking its perimeter and marks points as they go
- **THEN** the system SHALL append a polygon vertex at the device's current GPS position for each mark
- **AND** it SHALL let the curator close the polygon and save it as a `game.Zone`

#### Scenario: Tapping and adjusting vertices

- **WHEN** a curator taps the map to place, drag, or remove vertices of a new or existing Zone
- **THEN** the system SHALL update the Zone's `PolygonField` accordingly
- **AND** saving SHALL persist the adjusted boundary
