## MODIFIED Requirements

### Requirement: Challenge definition

The system SHALL model a `game.Challenge` with text content and a difficulty level, either bound to a specific tower or reusable as a generic challenge, and optionally carrying ordered media drawn from its Game's media library.

#### Scenario: Creating a challenge

- **WHEN** an administrator creates a challenge
- **THEN** it SHALL have text content and an integer difficulty level (typically 1-5)
- **AND** it SHALL either be bound to a specific tower (tower-specific) or be generic (reusable across any tower)
- **AND** it SHALL carry a `game` foreign key so it is shared across every Session of that Game

#### Scenario: A challenge may carry media

- **WHEN** an administrator attaches media to a challenge
- **THEN** the challenge SHALL carry one or more ordered media items from its Game's library (see the `challenge-media` capability)
- **AND** a challenge with no media SHALL behave exactly as a text-only challenge does

### Requirement: Challenges API

The system SHALL expose challenges over a REST API, including each challenge's media.

#### Scenario: Listing challenges

- **WHEN** a client requests `GET /api/challenges/`
- **THEN** the system SHALL return the current Session's Game challenges, including both tower-specific and generic challenges

#### Scenario: Media in the challenge payload

- **WHEN** a challenge carrying media is returned to a client permitted to see that challenge
- **THEN** each media item SHALL be reported in the creator's order with its kind, URL, caption, and alt text
- **AND** a challenge withheld from that client SHALL report no media and no media URLs
