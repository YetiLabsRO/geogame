## MODIFIED Requirements

### Requirement: Staff SPA scope

The system SHALL provide a staff app for the most common operational tasks, gated to staff users, and usable on both web and mobile — including an on-site mobile field authoring mode for building game elements in the field.

#### Scenario: Staff capabilities

- **WHEN** a staff user opens the app
- **THEN** it SHALL provide a pending review queue, tower/zone/team CRUD, challenge management, invite management, a live scoreboard, a live game overview, Game/Session management panels, session replay, and the game simulator
- **AND** those destinations SHALL be reachable from grouped navigation that shows the current location
- **AND** access SHALL be gated behind `is_staff=True`
- **AND** a visible "Django Admin" link SHALL remain for rare operations the staff UI does not cover

#### Scenario: Web and mobile field authoring

- **WHEN** a staff curator opens the app on a mobile device while on site
- **THEN** the app SHALL offer a field authoring mode for building game elements in the field — dropping towers at the current GPS position, attaching reference photos, drawing or adjusting zones, attaching challenges, and filing them into a target Collection (see the `field-authoring` capability)
- **AND** the same authoring surface SHALL remain available on the web for desk-based editing

## ADDED Requirements

### Requirement: The live overview is reachable from the staff app

The system SHALL let staff reach a Session's live overview and manage its share links without leaving the staff app.

#### Scenario: Reaching the overview

- **WHEN** a staff user is viewing a Session
- **THEN** the app SHALL offer a link to that Session's live overview
- **AND** the overview SHALL open on the map-and-standings view described by the `live-overview` capability

#### Scenario: Managing share links

- **WHEN** a staff user opens a Session's console
- **THEN** the app SHALL list that Session's share links with their labels and status
- **AND** it SHALL offer creating a link, copying its address, and revoking it
- **AND** a revoked link SHALL be shown as revoked rather than removed from view

#### Scenario: The share route is not gated as staff

- **WHEN** a viewer with no account opens a share link's address in the staff app
- **THEN** the app SHALL render the overview rather than redirecting to the staff login
- **AND** it SHALL render none of the staff navigation, share-link management, or game controls
