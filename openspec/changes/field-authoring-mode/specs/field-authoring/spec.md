## ADDED Requirements

### Requirement: Field authoring mode

The system SHALL provide a mobile field authoring mode in the staff app so curators can build game elements on site while scouting physical locations, targeting a Collection for everything they create.

#### Scenario: Entering field authoring on site

- **WHEN** a staff curator opens field authoring mode on a mobile device and grants location permission
- **THEN** the system SHALL center the map on the device's current GPS position
- **AND** it SHALL prompt the curator to select a target Collection (see the `collections` capability) for elements created in this session
- **AND** the mode SHALL present large, one-handed touch controls suitable for outdoor, on-site use
- **AND** access SHALL be gated to staff authorised to author the target Collection (see the `game-authoring-roles` capability)

#### Scenario: No location available

- **WHEN** the device cannot obtain a GPS fix or location permission is denied
- **THEN** the system SHALL inform the curator that GPS-based placement is unavailable
- **AND** it SHALL allow manual placement on the map as a fallback

### Requirement: Drop a tower at the current GPS position

The system SHALL let a curator create a Tower at the device's current GPS position with a single action.

#### Scenario: Dropping a tower where the curator stands

- **WHEN** a curator taps "drop tower here"
- **THEN** the system SHALL read the current geolocation and create a `game.Tower` whose `PointField` is set to that position
- **AND** it SHALL display the reading's accuracy in metres and record it as capture provenance on the tower
- **AND** the curator SHALL be able to nudge or re-read the position before the tower is saved

#### Scenario: Poor accuracy warning

- **WHEN** the current GPS accuracy is worse than a configured threshold
- **THEN** the system SHALL warn the curator before saving
- **AND** it SHALL offer to average multiple readings or retry so the stored position is usable for capture

### Requirement: Attach reference photos to a tower in the field

The system SHALL let a curator capture and attach one or more reference photos to a Tower while on site.

#### Scenario: Photographing the objective

- **WHEN** a curator captures a photo for a Tower being authored
- **THEN** the system SHALL store it as a `game.TowerPhoto` linked to that Tower, recording who captured it and when
- **AND** the photo SHALL serve as a reference image that helps players recognise the physical objective, distinct from player challenge submissions
- **AND** a Tower MAY have multiple reference photos

### Requirement: Draw and adjust zones on site

The system SHALL let a curator draw a new Zone polygon or adjust an existing one directly on the mobile map.

#### Scenario: Walking the boundary

- **WHEN** a curator chooses to draw a zone by walking its perimeter and marks points as they go
- **THEN** the system SHALL append a polygon vertex at the device's current GPS position for each mark
- **AND** it SHALL let the curator close the polygon and save it as a `game.Zone`

#### Scenario: Tapping and adjusting vertices

- **WHEN** a curator taps the map to place, drag, or remove vertices of a new or existing Zone
- **THEN** the system SHALL update the Zone's `PolygonField` accordingly
- **AND** saving SHALL persist the adjusted boundary

### Requirement: Attach challenges in the field

The system SHALL let a curator attach challenges to a Tower while on site.

#### Scenario: Adding a challenge on location

- **WHEN** a curator attaches a challenge to a Tower in field authoring mode
- **THEN** the system SHALL let them create a new Challenge or select an existing one and associate it with the Tower
- **AND** the association SHALL be persisted so players encounter that challenge at the Tower

### Requirement: Add field elements to the target Collection

The system SHALL add Towers and Zones created or adjusted in field authoring mode to the session's active target Collection.

#### Scenario: New geometry joins the collection

- **WHEN** a curator saves a newly dropped Tower or drawn Zone in field authoring mode
- **THEN** the system SHALL add it to the active target Collection (see the `collections` capability) so it becomes part of that reusable map
- **AND** the curator SHALL be able to switch the target Collection for subsequently created elements

#### Scenario: Staging drafts before publishing

- **WHEN** a curator wants to scout without exposing incomplete geometry to live games
- **THEN** the system SHALL allow field-created Towers to be saved as inactive drafts (reusing the Tower `is_active` flag)
- **AND** an inactive draft tower SHALL be excluded from live session scoping until the curator activates it

### Requirement: Offline-tolerant capture and sync

The system SHALL let a curator capture field-authoring edits without connectivity and sync them when the device is back online.

#### Scenario: Capturing offline

- **WHEN** a curator drops towers, captures photos, or draws zones while the device has no network connection
- **THEN** the system SHALL queue those edits locally on the device so they survive reload
- **AND** it SHALL indicate that the edits are pending sync

#### Scenario: Syncing on reconnect

- **WHEN** network connectivity is restored
- **THEN** the system SHALL upload the queued Towers, Zones, photos, and challenge associations to the server
- **AND** it SHALL surface any items that failed to sync so the curator can retry them
