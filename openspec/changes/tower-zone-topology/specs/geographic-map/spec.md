## ADDED Requirements

### Requirement: Overlapping zones and shared towers

The system SHALL model tower–zone membership as a many-to-many relationship, permitting a single Tower to belong to several Zones and permitting Zones to overlap and share Towers.

#### Scenario: A tower in multiple zones

- **WHEN** an administrator adds a tower to more than one zone
- **THEN** the system SHALL accept the membership without requiring the zones to be disjoint
- **AND** each such Zone SHALL independently count that tower among its member towers for control purposes (see the `scoring` capability)

#### Scenario: Zones sharing a tower may overlap geographically

- **WHEN** two zones' polygons overlap
- **THEN** the system SHALL NOT reject the overlap
- **AND** a tower MAY be a member of both overlapping zones at the same time

### Requirement: Tower–zone membership is logical, not spatial

The system SHALL treat tower–zone membership as an explicit logical link and SHALL NOT require a Tower to lie geographically inside the Zones it belongs to, nor infer membership from geometry.

#### Scenario: Linking a tower outside a zone's polygon

- **WHEN** an administrator adds a tower whose point falls outside a zone's polygon to that zone
- **THEN** the system SHALL accept the membership
- **AND** the tower SHALL contribute to that zone's control exactly as if it were inside the polygon

#### Scenario: Membership is never inferred from geometry

- **WHEN** a tower's point happens to fall inside a zone's polygon
- **THEN** the system SHALL NOT automatically add the tower to that zone
- **AND** membership SHALL change only through an explicit add or remove action

### Requirement: Every zone has at least one tower

The system SHALL enforce that every `Zone` retains at least one member `Tower`.

#### Scenario: Rejecting removal of a zone's last tower

- **WHEN** an operation would leave a Zone with zero member towers — removing its last membership, or deleting the last tower that belongs to it
- **THEN** the system SHALL reject the operation with a validation error
- **AND** the Zone SHALL retain at least one member tower

#### Scenario: Autocreated circle zone starts with its founding tower

- **WHEN** a tower is saved with `autocreate_zone` set and it currently has no zones
- **THEN** the system SHALL create a circular Zone and add it to that tower's `zones`
- **AND** the new Zone SHALL therefore satisfy the at-least-one-tower invariant from creation

## MODIFIED Requirements

### Requirement: Zone definition

The system SHALL model a `game.Zone` as a geographic polygon that groups towers through a many-to-many membership and awards area-wide points to the team controlling it, living in the repository and reachable by Games through Collection membership.

#### Scenario: Creating a zone

- **WHEN** an administrator creates a zone
- **THEN** the system SHALL store a `PolygonField` boundary, a human-readable name, a display color, and a `score_type` strategy
- **AND** the `score_type` SHALL be one of `LINEAR`, `LOGARITHMIC`, `EXPONENTIAL`, or `BONUS` (the per-strategy scoring formulas are defined by the `scoring` capability)

#### Scenario: Zone belongs to the repository

- **WHEN** a zone is created
- **THEN** it SHALL NOT carry a mandatory `game` foreign key
- **AND** it SHALL be associated with Games through membership in one or more `Collection`s (see the `collections` capability), so the same zone is reusable across every Game whose collections include it

#### Scenario: Zone groups towers many-to-many

- **WHEN** towers are associated with a zone
- **THEN** the association SHALL be a many-to-many relationship, so a single tower MAY belong to several zones and a single zone MAY share towers with other, possibly overlapping, zones

### Requirement: Tower definition

The system SHALL model a `game.Tower` as a geographic point that teams capture as a physical objective, living in the repository and reachable by Games through Collection membership, and belonging to zero or more Zones through a many-to-many `zones` relationship.

#### Scenario: Creating a tower

- **WHEN** an administrator creates a tower
- **THEN** the system SHALL store its location as a `PointField` and a name
- **AND** the tower SHALL NOT carry a mandatory `game` foreign key; its association to any Game SHALL be derived through `Collection` membership (see the `collections` capability)
- **AND** the tower's zone membership SHALL be expressed as a many-to-many `zones` relationship (not a single `zone` foreign key), so the same tower MAY belong to several zones at once
- **AND** the tower SHALL carry a `category` of `NORMAL` (GPS-verified capture) or `RFID` (tag-scanned capture)
- **AND** the tower SHALL carry an `is_active` flag and an `initial_bonus` integer

#### Scenario: RFID tower requires a code

- **WHEN** a tower's category is `RFID`
- **THEN** the tower SHALL have a unique `rfid_code` used for tag-based capture (see the `rfid-capture` capability)

#### Scenario: Deactivating a tower releases ownership

- **WHEN** a tower's `is_active` flag is set to `False`
- **THEN** the system SHALL close all of the tower's current team ownerships
- **AND** for every Zone in the tower's `zones` the system SHALL recompute zone control and close or reopen zone ownerships as required (see the `scoring` capability)

### Requirement: Live map data with ownership coloring

The system SHALL expose the current Session's zones and active towers — resolved through its Game's collections — over a REST API so clients can render a live map colored by current control, including each tower's zone memberships.

#### Scenario: Fetching zones

- **WHEN** a client requests `GET /api/zones/`
- **THEN** the system SHALL return the zones reachable through the caller's current Session's Game collections, as GeoJSON (via `rest_framework_gis`) with current per-TeamGroup ownership coloring
- **AND** an optional `group` query parameter SHALL color the zones by the named TeamGroup

#### Scenario: Fetching towers with proximity filtering

- **WHEN** a client requests `GET /api/towers/`
- **THEN** the system SHALL return only active towers reachable through the caller's current Session's Game collections, as GeoJSON
- **AND** each tower's payload SHALL express its zone membership as a list of zones (its `zones`), not a single zone
- **AND** it SHALL accept optional `lat`, `lng`, and `accuracy` query parameters for proximity filtering
