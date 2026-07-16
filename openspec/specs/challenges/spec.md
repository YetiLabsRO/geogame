# Challenges Specification

## Purpose

Model the text-based Challenges teams solve to capture towers, and the "next challenge" selection that structures a team's progression at a tower.

## Requirements

### Requirement: Challenge definition

The system SHALL model a `game.Challenge` with text content and a difficulty level, either bound to a specific tower or reusable as a generic challenge.

#### Scenario: Creating a challenge

- **WHEN** an administrator creates a challenge
- **THEN** it SHALL have text content and an integer difficulty level (typically 1-5)
- **AND** it SHALL either be bound to a specific tower (tower-specific) or be generic (reusable across any tower)
- **AND** it SHALL carry a `game` foreign key so it is shared across every Session of that Game

### Requirement: Next-challenge selection

The system SHALL serve the correct next challenge for the tower a team is standing at, based on the highest difficulty that team has already conquered at that tower.

#### Scenario: Selection order

- **WHEN** a team requests the next challenge for a tower
- **THEN** the system SHALL select, in order:
  1. the lowest-difficulty tower-specific challenge not yet conquered, then
  2. generic challenges in ascending difficulty, then
  3. once all are exhausted, the hardest generic challenge as an infinite replay fallback

#### Scenario: Progression is per-tower

- **WHEN** the next challenge is computed
- **THEN** the calculation SHALL be based on the highest difficulty the team has already conquered at that specific tower

### Requirement: Challenges API

The system SHALL expose challenges over a REST API.

#### Scenario: Listing challenges

- **WHEN** a client requests `GET /api/challenges/`
- **THEN** the system SHALL return the current Session's Game challenges, including both tower-specific and generic challenges
