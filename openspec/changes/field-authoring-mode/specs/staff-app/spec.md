## MODIFIED Requirements

### Requirement: Staff SPA scope

The system SHALL provide a staff app for the most common operational tasks, gated to staff users, and usable on both web and mobile — including an on-site mobile field authoring mode for building game elements in the field.

#### Scenario: Staff capabilities

- **WHEN** a staff user opens the app
- **THEN** it SHALL provide a pending review queue, tower/zone/team CRUD, challenge management, invite management, a live scoreboard, and Game/Session management panels
- **AND** access SHALL be gated behind `is_staff=True`
- **AND** a visible "Django Admin" link SHALL remain for rare operations the staff UI does not cover

#### Scenario: Web and mobile field authoring

- **WHEN** a staff curator opens the app on a mobile device while on site
- **THEN** the app SHALL offer a field authoring mode for building game elements in the field — dropping towers at the current GPS position, attaching reference photos, drawing or adjusting zones, attaching challenges, and filing them into a target Collection (see the `field-authoring` capability)
- **AND** the same authoring surface SHALL remain available on the web for desk-based editing
