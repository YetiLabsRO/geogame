# Session History & Visibility Specification

## Purpose

Retain past Sessions as historical records and expose read-only views of their final state to staff and to the players who participated.

## Requirements

### Requirement: Sessions are retained

The system SHALL never hard-delete Sessions; they are kept as historical records.

#### Scenario: A session ends

- **WHEN** a Session is deactivated or its run ends
- **THEN** the system SHALL retain the Session and all its ownership records rather than deleting them

### Requirement: Staff history views

The system SHALL let staff browse past Sessions and their final state.

#### Scenario: Browsing past sessions

- **WHEN** a staff member opens the "Past sessions" list
- **THEN** the list SHALL be filterable by Game
- **AND** each past Session SHALL offer a read-only view of its final scoreboard and ownership timeline

### Requirement: Player history views

The system SHALL let players view past Sessions they participated in.

#### Scenario: Viewing own past sessions

- **WHEN** a player opens their session list
- **THEN** it SHALL include all Sessions where they have or had a `TeamMembership`, active or inactive
- **AND** each read-only past-session view SHALL show the final scoreboard and their team's ownership timeline
