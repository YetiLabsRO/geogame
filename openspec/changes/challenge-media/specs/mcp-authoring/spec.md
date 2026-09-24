## ADDED Requirements

### Requirement: Media library read surface

The system SHALL provide a read tool that returns the creator's media library for a Game, so the LLM can compose multi-modal challenges from assets that already exist rather than inventing references.

#### Scenario: Listing a game's media

- **WHEN** the LLM calls `list_media` for a Game it may author
- **THEN** the server SHALL return that Game's library items with their id, kind, alt text, and duration where applicable
- **AND** the result SHALL exclude the libraries of Games outside that creator's authoring scope

#### Scenario: The LLM never supplies media itself

- **WHEN** the LLM attaches media to a suggested Challenge
- **THEN** it SHALL do so by library id only
- **AND** the server SHALL NOT accept an uploaded file, a data URI, or a URL from the LLM
- **AND** the system SHALL NOT fetch any resource on the LLM's behalf at stage or apply time

## MODIFIED Requirements

### Requirement: LLM suggests challenge ideas from town context

The system SHALL let the LLM take the information it holds about a town and stage suggested Challenges, each carrying a rationale and optionally referencing media from the Game's library, so a creator receives a reviewable draft Challenge bank.

#### Scenario: Suggesting challenges

- **WHEN** the LLM calls `suggest_challenge` with proposed text, a difficulty, a tower-specific or generic binding, and a target Game
- **THEN** the server SHALL stage each suggestion as a proposed Challenge operation with the LLM's `rationale` attached
- **AND** it SHALL accept several suggestions in one call, staging each as its own operation
- **AND** none of the suggested Challenges SHALL exist as real records until the proposal is approved and applied

#### Scenario: Suggesting a challenge with media

- **WHEN** the LLM calls `suggest_challenge` with one or more media library ids and their order
- **THEN** the server SHALL stage the Challenge operation with those references and their order
- **AND** the applied Challenge SHALL carry that media in that order

#### Scenario: An unusable media reference is refused

- **WHEN** a suggested Challenge references a media id that does not exist, belongs to another Game, or is outside the creator's authoring scope
- **THEN** the server SHALL refuse to stage the operation and report which reference failed
- **AND** the apply engine SHALL re-check every reference and fail the operation rather than apply a Challenge with a dangling attachment
