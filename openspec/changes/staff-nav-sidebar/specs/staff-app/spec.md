## ADDED Requirements

### Requirement: Every staff destination is reachable by navigation

The system SHALL make every route the staff app serves reachable from its navigation, at every supported viewport width.

#### Scenario: Reaching any destination

- **WHEN** a staff user opens the app at any supported width
- **THEN** every top-level staff route SHALL be reachable by clicking, without typing a URL
- **AND** no navigation entry SHALL be positioned outside the visible viewport

#### Scenario: A route with no navigation entry

- **WHEN** the staff app serves a top-level route that no navigation entry points to
- **THEN** that is a defect in this requirement, regardless of the page itself working

### Requirement: Navigation is grouped into labelled sections

The system SHALL present staff destinations in labelled groups rather than as a flat list.

#### Scenario: Reading the navigation

- **WHEN** a staff user looks at the navigation
- **THEN** destinations SHALL be grouped under visible section labels reflecting when each screen is used — running a game, building one, organising who plays, and analysing afterwards
- **AND** each destination SHALL appear in exactly one section

### Requirement: Navigation shows the current location

The system SHALL indicate which destination is currently open.

#### Scenario: Viewing a staff page

- **WHEN** a staff user is on any staff page
- **THEN** the navigation SHALL mark that page's entry as active
- **AND** the entry's section SHALL remain visible, so the user can see where they are

### Requirement: Navigation adapts to small screens

The system SHALL keep the staff app usable at phone width.

#### Scenario: Opening the app on a phone

- **WHEN** a staff user opens the app below the layout's wide breakpoint
- **THEN** the navigation SHALL collapse behind a control rather than consuming or overflowing the page
- **AND** activating that control SHALL reveal the full grouped navigation
- **AND** choosing a destination SHALL dismiss it and show the page

#### Scenario: Opening the app on a wide screen

- **WHEN** a staff user opens the app at the wide breakpoint or above
- **THEN** the navigation SHALL be visible without any interaction

## MODIFIED Requirements

### Requirement: Staff SPA scope

The system SHALL provide a staff app for the most common operational tasks, gated to staff users, and usable on both web and mobile — including an on-site mobile field authoring mode for building game elements in the field.

#### Scenario: Staff capabilities

- **WHEN** a staff user opens the app
- **THEN** it SHALL provide a pending review queue, tower/zone/team CRUD, challenge management, invite management, a live scoreboard, Game/Session management panels, session replay, and the game simulator
- **AND** those destinations SHALL be reachable from grouped navigation that shows the current location
- **AND** access SHALL be gated behind `is_staff=True`
- **AND** a visible "Django Admin" link SHALL remain for rare operations the staff UI does not cover

#### Scenario: Web and mobile field authoring

- **WHEN** a staff curator opens the app on a mobile device while on site
- **THEN** the app SHALL offer a field authoring mode for building game elements in the field — dropping towers at the current GPS position, attaching reference photos, drawing or adjusting zones, attaching challenges, and filing them into a target Collection (see the `field-authoring` capability)
- **AND** the same authoring surface SHALL remain available on the web for desk-based editing
