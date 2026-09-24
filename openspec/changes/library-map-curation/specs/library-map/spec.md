## ADDED Requirements

### Requirement: The repository is curated on a map

The system SHALL present the repository of Towers and Zones as a map, and SHALL let staff curate Collection membership directly on it.

#### Scenario: Seeing the library

- **WHEN** a staff user opens the library
- **THEN** the system SHALL draw every repository tower and zone in its real position
- **AND** each tower SHALL be drawn with its resolved styling, so kinds of place are distinguishable at a glance
- **AND** the view SHALL not be scoped to any Game or Session

#### Scenario: Seeing a collection

- **WHEN** a staff user selects a Collection
- **THEN** the system SHALL distinguish that Collection's members from the rest of the library on the map
- **AND** it SHALL state how many towers and zones the Collection holds

#### Scenario: Changing membership from the map

- **WHEN** a staff user acts on a tower or zone while a Collection is selected
- **THEN** the system SHALL add it to, or remove it from, that Collection
- **AND** the map SHALL reflect the change without a reload

#### Scenario: Curation never destroys geometry

- **WHEN** a tower or zone is removed from a Collection
- **THEN** the underlying repository row SHALL survive
- **AND** it SHALL remain visible in the library and in any other Collection holding it

#### Scenario: An element in several collections

- **WHEN** a tower or zone belongs to more than one Collection
- **THEN** the system SHALL say so when it is inspected
- **AND** removing it from one Collection SHALL leave the others untouched

### Requirement: Finding things in a large library

The system SHALL let staff narrow the library by name and by tower type.

#### Scenario: Searching

- **WHEN** a staff user searches or filters the library
- **THEN** the map and the accompanying list SHALL show the same narrowed set
- **AND** clearing the search SHALL restore the whole library

#### Scenario: Locating one element

- **WHEN** a staff user selects an element from the list
- **THEN** the map SHALL bring it into view

### Requirement: The library is served in one request

The system SHALL expose the repository's geometry, styling, media counts and collection membership as a single response.

#### Scenario: Drawing the library

- **WHEN** a client renders the library map
- **THEN** it SHALL obtain every element it draws from one request
- **AND** it SHALL NOT need a request per element to learn an element's styling, its media, or which Collections hold it
