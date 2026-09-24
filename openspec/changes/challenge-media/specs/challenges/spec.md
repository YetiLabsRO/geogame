## MODIFIED Requirements

### Requirement: Challenge definition

The system SHALL model a `game.Challenge` with text content and a difficulty level, either bound to a specific tower or reusable as a generic challenge, and optionally carrying its own ordered media.

#### Scenario: Creating a challenge

- **WHEN** an administrator creates a challenge
- **THEN** it SHALL have text content and an integer difficulty level (typically 1-5)
- **AND** it SHALL either be bound to a specific tower (tower-specific) or be generic (reusable across any tower)
- **AND** it SHALL carry a `game` foreign key so it is shared across every Session of that Game

#### Scenario: A challenge may carry media

- **WHEN** an administrator attaches media to a challenge
- **THEN** the challenge SHALL carry one or more ordered media items as its own content (see the `challenge-media` capability)
- **AND** a challenge with no media SHALL behave exactly as a text-only challenge does

#### Scenario: A tower-bound challenge need not be about its tower

- **WHEN** a challenge is bound to a tower and its content is carried by its media
- **THEN** the challenge SHALL be served at that tower as any tower-specific challenge is
- **AND** the team SHALL remain subject to the same proximity and presence rules as any other challenge at that tower

### Requirement: Challenges API

The system SHALL expose challenges over a REST API, including each challenge's media.

#### Scenario: Listing challenges

- **WHEN** a client requests `GET /api/challenges/`
- **THEN** the system SHALL return the current Session's Game challenges, including both tower-specific and generic challenges

#### Scenario: Media in the challenge payload

- **WHEN** a challenge carrying media is returned to a client permitted to see that challenge
- **THEN** each media item SHALL be reported in the creator's order with its kind, URL, caption, and alt text
- **AND** a challenge withheld from that client SHALL report no media and no media URLs
