# Scoring Specification

## Purpose

Define how teams earn points — instantly on capture (locked points) and continuously for zone control (floating points) — including the four zone score functions and majority-rule zone control.

## Requirements

### Requirement: Locked and floating score

The system SHALL track each team's score as a locked component plus a dynamically-computed floating component.

#### Scenario: Computing current score

- **WHEN** a team's `current_score()` is evaluated
- **THEN** it SHALL return `score` (locked, cumulative points) plus `floating_score` (points from currently-active zone ownerships)

### Requirement: Zone score functions

The system SHALL compute a zone's floating points using the zone's configured `score_type`, where `mins` is the duration of the current ownership window in minutes.

#### Scenario: Applying each strategy

- **WHEN** floating points are computed for a held zone
- **THEN** the value SHALL be:
  - `LINEAR`: `mins`
  - `LOGARITHMIC`: `30 × ln(mins) + mins² / 10000`
  - `EXPONENTIAL` and `BONUS`: `min(mins² / 25 + 50, 200)`

### Requirement: Majority-rule zone control

The system SHALL grant a zone to the team controlling a strict majority of that zone's currently-active towers, computed per TeamGroup.

#### Scenario: Recomputing on tower ownership change

- **WHEN** tower ownership changes
- **THEN** the system SHALL recompute zone control per TeamGroup
- **AND** on a change of controller, the prior owner's `TeamZoneOwnership` SHALL be closed (its floating score finalized and added to the locked `score`) and a new `TeamZoneOwnership` SHALL be opened for the new controller, if any

### Requirement: Initial bonus on capture

The system SHALL add a tower's `initial_bonus` to the capturing team's locked score at the moment of capture.

#### Scenario: Awarding the bonus

- **WHEN** a tower is assigned to a team via `tower.assign_to_team(team)`
- **THEN** the system SHALL add `tower.initial_bonus` to that team's locked `score`
