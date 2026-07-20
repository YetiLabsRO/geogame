## ADDED Requirements

### Requirement: Tower hold interval accrues under any lock mode

The system SHALL accrue points for a team over the interval it holds a tower — from winning it until the next team takes it — independent of the effective `tower_lock_mode`, through the `TeamTowerOwnership` window that feeds zone control (see the `scoring` capability).

#### Scenario: Accrual under FREE_FOR_ALL

- **WHEN** a team captures a tower under `FREE_FOR_ALL` and later another team captures the same tower
- **THEN** the first team's `TeamTowerOwnership` window SHALL run from its capture until the second team's capture
- **AND** that window SHALL contribute to the team's zone control (and thus its floating score) for exactly that interval (see the zone-control computation in the `scoring` capability)

#### Scenario: Accrual under LOCK_ON_INITIATE

- **WHEN** a team captures a tower under `LOCK_ON_INITIATE` and later a different team locks and finishes the same tower
- **THEN** the first team's `TeamTowerOwnership` window SHALL run from its capture until the second team's capture, just as under `FREE_FOR_ALL`
- **AND** locking SHALL change only which team is eligible to capture and when, not how the hold interval accrues

### Requirement: A lock without a confirmed finish accrues nothing

The system SHALL NOT open any ownership window or award any points for a `TowerLock` that expires or is cancelled without a confirmed finish.

#### Scenario: Expired lock awards nothing

- **WHEN** a `TowerLock` reaches `expires_at` (or is `CANCELLED`) without a confirmed `TeamTowerChallenge`
- **THEN** the system SHALL NOT call `tower.assign_to_team` for that lock
- **AND** it SHALL NOT open a `TeamTowerOwnership` window for the locking team
- **AND** it SHALL NOT award the tower's `initial_bonus`

## MODIFIED Requirements

### Requirement: Initial bonus on capture

The system SHALL add a tower's `initial_bonus` to the capturing team's locked score at the moment of capture — that is, on a confirmed finish — and SHALL never award it for merely locking or initiating a tower.

#### Scenario: Awarding the bonus

- **WHEN** a tower is assigned to a team via `tower.assign_to_team(team)`
- **THEN** the system SHALL add `tower.initial_bonus` to that team's locked `score`

#### Scenario: Locking alone awards no bonus

- **WHEN** a team acquires a `TowerLock` on a tower under `LOCK_ON_INITIATE` but has not yet had a submission confirmed
- **THEN** the system SHALL NOT award `tower.initial_bonus`
- **AND** the bonus SHALL be awarded only if and when the team's finish is confirmed and `tower.assign_to_team` runs
