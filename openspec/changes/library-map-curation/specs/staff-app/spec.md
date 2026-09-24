## ADDED Requirements

### Requirement: The library map is reachable from the staff app

The system SHALL make the map-first library a named destination in the staff app.

#### Scenario: Reaching the library

- **WHEN** a staff user opens the staff app
- **THEN** the library SHALL be reachable from the navigation

#### Scenario: A previously bookmarked collections link

- **WHEN** a staff user follows an existing link to the collections page
- **THEN** the system SHALL take them to the library rather than failing
