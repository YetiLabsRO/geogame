## ADDED Requirements

### Requirement: Legacy database import

The system SHALL import game content from a PostgreSQL dump of a pre-Session installation, landing it in the current schema.

#### Scenario: Importing a legacy dump

- **WHEN** an administrator runs the legacy import command against a dump of the pre-Session schema, naming a target Collection and Game
- **THEN** the system SHALL create a Zone for each legacy zone, preserving its name, colour, scoring type and shape
- **AND** it SHALL create a Tower for each legacy tower, preserving its name, position, category, active flag and RFID code
- **AND** each imported Tower SHALL be a member of the Zone its legacy row named
- **AND** it SHALL create a Challenge for each legacy challenge, preserving its text and difficulty, attached to its Tower when it named one and to the Game alone when it did not
- **AND** it SHALL place every imported Zone and Tower in the named Collection, and link that Collection to the named Game

#### Scenario: Legacy team categories

- **WHEN** the legacy dump holds teams in the hardcoded categories that preceded TeamGroups
- **THEN** the system SHALL create one TeamGroup on the imported Game per category present
- **AND** it SHALL NOT import the legacy teams, their rosters or their scores

#### Scenario: Re-running the import

- **WHEN** the command is run again for a Collection that already holds content
- **THEN** it SHALL refuse rather than duplicate, unless replacement is explicitly requested
- **AND** when replacement is requested it SHALL replace that Collection's imported content

#### Scenario: A value that cannot be landed

- **WHEN** a legacy row carries a value the current schema cannot accept, such as an RFID code another Tower already holds
- **THEN** the system SHALL import the rest of the row and report what it dropped and why

#### Scenario: Nothing is assumed about the dump

- **WHEN** the named dump is not a readable dump of the expected legacy schema
- **THEN** the system SHALL fail with what it found, before writing anything
