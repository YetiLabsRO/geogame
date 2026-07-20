## ADDED Requirements

### Requirement: Collections group repository geometry

The system SHALL model `game.Collection` as a named, reusable grouping of Towers and Zones, so the same geometry can be composed into many maps.

#### Scenario: Creating a collection

- **WHEN** a creator creates a Collection
- **THEN** it SHALL have a `name`, a URL-safe `slug`, an optional `description`, `created_by`, and `created_at`
- **AND** it SHALL relate to Towers and Zones through many-to-many memberships, so a Tower or Zone MAY belong to more than one Collection

#### Scenario: Curating membership

- **WHEN** a creator adds or removes a Tower or Zone from a Collection
- **THEN** the change SHALL affect only Collection membership and SHALL NOT delete the Tower or Zone from the repository
- **AND** removing the last Collection link from a Tower or Zone SHALL leave it as an orphan library asset, not delete it

### Requirement: Towers and Zones are repository assets

The system SHALL treat Towers and Zones as repository (library) assets that are not owned by a single Game, discoverable and reusable independent of any Game.

#### Scenario: Geometry has no single-game owner

- **WHEN** a Tower or Zone is created in the repository
- **THEN** it SHALL NOT carry a mandatory `game` foreign key
- **AND** its association to any Game SHALL be derived through Collection membership (see the `game-configuration` capability)

### Requirement: Collections API

The system SHALL expose Collections and their membership over a staff/creator REST API.

#### Scenario: Managing collections

- **WHEN** a creator calls `GET/POST/PATCH/DELETE /api/staff/collections/`
- **THEN** the system SHALL let them list, create, edit, and delete Collections they may author
- **AND** dedicated actions SHALL add or remove Towers and Zones from a Collection

#### Scenario: Usage visibility before edits

- **WHEN** a creator views a Tower or Zone in the repository
- **THEN** the system SHALL report which Collections and which Games currently reference it, so edits and deletes are made with awareness of shared usage
