## MODIFIED Requirements

### Requirement: Staff history views

The system SHALL let staff browse past Sessions and their final state, and replay how that state came about.

#### Scenario: Browsing past sessions

- **WHEN** a staff member opens the "Past sessions" list
- **THEN** the list SHALL be filterable by Game
- **AND** each past Session SHALL offer a read-only view of its final scoreboard and ownership timeline

#### Scenario: Replaying a past session

- **WHEN** a staff member opens a past Session's read-only view
- **THEN** it SHALL offer an entry point to replay the Session over time (see the `session-replay` capability)
- **AND** the replay SHALL remain available for as long as the Session's underlying history survives retention
