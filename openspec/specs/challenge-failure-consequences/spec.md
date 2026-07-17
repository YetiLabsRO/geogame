# challenge-failure-consequences Specification

## Purpose
TBD - created by archiving change day-pausing-and-failure-consequences. Update Purpose after archive.
## Requirements
### Requirement: Failure penalty configuration

The system SHALL expose combinable failure-penalty knobs on `Game` as defaults, each independently toggleable and each overridable per `Session`, all defaulting to "off" so existing behavior is unchanged.

#### Scenario: Default knob values

- **WHEN** a Game is created
- **THEN** it SHALL default `fail_point_penalty` to `0`, `fail_cooloff_scaling` to `1.0`, `fail_tower_lockout_minutes` to `0`, and `fail_difficulty_rollback` to `False`
- **AND** with these defaults a rejected submission SHALL behave exactly as it does today (5-minute cooloff only)

#### Scenario: Per-session override wins

- **WHEN** a Session sets an override for a failure knob
- **THEN** the effective value for that Session SHALL be the Session override, otherwise the Game default

### Requirement: Point penalty on rejection

The system SHALL subtract a configurable penalty from a team's score each time a submission is rejected, never dropping below zero.

#### Scenario: Subtracting the penalty

- **WHEN** a `TeamTowerChallenge` is REJECTED and the effective `fail_point_penalty` is greater than `0`
- **THEN** the system SHALL atomically subtract `fail_point_penalty` from `Team.score`
- **AND** the resulting `score` SHALL NOT go below zero

### Requirement: Cooloff scaling by consecutive failures

The system SHALL scale a team's cooloff on a tower by its consecutive-fail count on that tower.

#### Scenario: Scaling the cooloff

- **WHEN** the effective cooloff for a `(team, tower)` pair is computed
- **THEN** it SHALL equal `base_cooloff × fail_cooloff_scaling ^ consecutive_fails_on_this_tower`

### Requirement: Tower lockout after rejection

The system SHALL block a team from resubmitting on a tower for a configurable duration after a rejection, independently of the cooloff.

#### Scenario: Locking out the team

- **WHEN** a submission is REJECTED and the effective `fail_tower_lockout_minutes` is greater than `0`
- **THEN** the team SHALL be blocked from resubmitting on that tower for that many minutes, independently of the cooloff window

### Requirement: Difficulty rollback after rejection

The system SHALL draw the next challenge from a lower difficulty bucket after a rejection when configured to do so.

#### Scenario: Rolling back difficulty

- **WHEN** the effective `fail_difficulty_rollback` is `True` and a team has an outstanding consecutive fail on a tower
- **THEN** the next-challenge selection for that tower SHALL be drawn from the next-lower difficulty bucket

### Requirement: Consecutive-fail counters and reset semantics

The system SHALL track consecutive-fail counters per `(team, tower)` and reset them according to a configurable rule.

#### Scenario: Reset on tower success only (default)

- **WHEN** `fail_counter_reset` is `TOWER_SUCCESS_ONLY`
- **THEN** the counter SHALL reset only on a CONFIRMED submission on the same tower, or when staff explicitly clear it

#### Scenario: Reset on any success elsewhere

- **WHEN** `fail_counter_reset` is `ANY_SUCCESS_ELSEWHERE`
- **THEN** a CONFIRMED submission on any other tower SHALL also reset the counter

#### Scenario: Reset on any attempt elsewhere

- **WHEN** `fail_counter_reset` is `ANY_ATTEMPT_ELSEWHERE`
- **THEN** any submission on any other tower, regardless of outcome, SHALL reset the counter

### Requirement: No cross-team side effects

The system SHALL confine all failure penalties to the failing team.

#### Scenario: Failures do not affect other teams

- **WHEN** a team's submission is rejected and penalties apply
- **THEN** no other team's score, challenge selection, cooloff, or lockout SHALL be affected

