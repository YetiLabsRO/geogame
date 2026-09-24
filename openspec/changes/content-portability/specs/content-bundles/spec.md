## ADDED Requirements

### Requirement: Portable content bundle

The system SHALL package selected Games and Collections, with the repository content they depend on, into a single portable file that another install of the system can read.

#### Scenario: Exporting a game

- **WHEN** a staff user exports a Game
- **THEN** the system SHALL produce one file containing that Game's configuration, its challenge bank, its roles, its team groups, its game-owned score multipliers and its trail when it has one
- **AND** the file SHALL also contain every Collection the Game links, and every Tower, Zone, tower type, presence requirement and tower photo those Collections reach
- **AND** the file SHALL contain the media files its content references

#### Scenario: Exporting a collection on its own

- **WHEN** a staff user exports a Collection without a Game
- **THEN** the system SHALL produce a file containing that Collection's Towers and Zones with their geometry, types and photos
- **AND** it SHALL include the challenges bound to those Towers only when a Game that owns them is also being exported

#### Scenario: Run data never travels

- **WHEN** any bundle is produced
- **THEN** it SHALL contain no Session, Team, Player, team membership, tower or zone ownership, submission, score, location ping, tower lock or discovery record
- **AND** it SHALL contain no user account, no user reference, and no NFC tag provisioning secret

#### Scenario: The bundle declares what wrote it

- **WHEN** a bundle is produced
- **THEN** it SHALL record a format version and the time of export

### Requirement: Stable content identity

The system SHALL give every exportable row an identifier that is stable across databases, so that content can be recognised after it travels.

#### Scenario: Identity survives a round trip

- **WHEN** content is exported from one install and imported into another, and then exported again
- **THEN** each row's identifier SHALL be unchanged through both trips

#### Scenario: Identity survives editing

- **WHEN** an imported row is renamed or otherwise edited
- **THEN** its identifier SHALL NOT change
- **AND** a later import of a bundle containing that row SHALL still recognise it as the same row

#### Scenario: Existing content is identified too

- **WHEN** the identifier is introduced to a database that already holds content
- **THEN** every existing row SHALL receive one
- **AND** no two rows SHALL share an identifier

### Requirement: Importing a bundle

The system SHALL import a content bundle, creating or updating content according to a mode the importer chooses.

#### Scenario: Importing content that is not here yet

- **WHEN** a bundle is imported into an install that holds none of its content
- **THEN** the system SHALL create every Game, Collection, Tower, Zone, challenge and supporting row the bundle carries
- **AND** every reference between them SHALL resolve to the newly created rows
- **AND** no row SHALL reference content from the source install

#### Scenario: Importing an updated bundle in sync mode

- **WHEN** a bundle is imported in sync mode and the install already holds rows with the same identifiers
- **THEN** the system SHALL update those rows from the bundle rather than creating duplicates
- **AND** rows in the bundle that are absent here SHALL be created

#### Scenario: Importing a second independent copy

- **WHEN** a bundle is imported in copy mode
- **THEN** the system SHALL create a wholly new copy of its content with fresh identifiers
- **AND** it SHALL leave every existing row untouched
- **AND** it SHALL make each new slug unique rather than failing on a collision

#### Scenario: An import that cannot complete

- **WHEN** any part of an import fails
- **THEN** the system SHALL leave the database exactly as it was before the import began

#### Scenario: A bundle from a future version

- **WHEN** a bundle declares a format version the system does not understand
- **THEN** the system SHALL refuse it and state the version it found
- **AND** it SHALL write nothing

#### Scenario: A malformed or hostile archive

- **WHEN** an archive contains entries that resolve outside the archive root, or exceeds the permitted entry count or uncompressed size
- **THEN** the system SHALL refuse the import and write nothing outside its own media storage

#### Scenario: A conflicting unique value

- **WHEN** an imported Tower carries an RFID code that another Tower here already holds
- **THEN** the system SHALL keep the existing Tower's code, import the rest of the Tower, and report the conflict

### Requirement: Inspecting a bundle before importing it

The system SHALL report what a bundle contains, and what importing it would do, without changing anything.

#### Scenario: Inspecting

- **WHEN** a staff user submits a bundle for inspection
- **THEN** the system SHALL report the bundle's format version and export time, and how many rows of each kind it carries
- **AND** it SHALL report which of those rows already exist in this install
- **AND** it SHALL report which slugs would collide
- **AND** it SHALL make no change to the database or to stored media

### Requirement: Export and import without shell access

The system SHALL expose export, inspection and import both as management commands and as staff-only endpoints.

#### Scenario: From the command line

- **WHEN** an administrator runs the export command naming games or collections
- **THEN** the system SHALL write a bundle file to the requested path
- **AND** the import command SHALL accept such a file and apply it in the requested mode

#### Scenario: Over HTTP

- **WHEN** a staff user requests an export through the API
- **THEN** the system SHALL return the bundle as a downloadable file
- **AND** the inspect and import endpoints SHALL accept an uploaded bundle

#### Scenario: Not for players

- **WHEN** a non-staff user calls any bundle endpoint
- **THEN** the system SHALL refuse the request
