## MODIFIED Requirements

### Requirement: Pause window model

The system SHALL model day cut-off pauses as `game.PauseWindow` records so a Session can be paused and resumed any number of times over its lifetime, and SHALL keep the explicit `PAUSED` lifecycle state in lockstep with the open-window predicate.

#### Scenario: A session is paused iff it has an open window

- **WHEN** the system evaluates whether a Session is paused
- **THEN** the Session SHALL be considered paused if and only if it has a `PauseWindow` with `ended_at IS NULL`
- **AND** a `PauseWindow` SHALL record `session`, `started_at`, a nullable `ended_at`, and the snapshots needed to restore ownerships on resume
- **AND** the `PauseWindow` model SHALL live in the `game` app alongside the ownership records it interacts with

#### Scenario: Open window and PAUSED state are equivalent

- **WHEN** the system evaluates a Session's lifecycle
- **THEN** `Session.state == PAUSED` SHALL hold if and only if the Session has a `PauseWindow` with `ended_at IS NULL` (see the `session-lifecycle` capability)
- **AND** `Session.is_paused()` SHALL return `state == PAUSED`, so the derived-pause notion and the explicit state can never disagree

### Requirement: Pause and resume endpoints

The system SHALL let staff open and close pause windows for a Session, transitioning the lifecycle `state` between `RUNNING` and `PAUSED` atomically with opening/closing the window, and closing and (optionally) restoring ownerships.

#### Scenario: Pausing closes and records ownerships

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/pause/`
- **THEN** the system SHALL transition the Session from `RUNNING` to `PAUSED` and open a `PauseWindow` in one atomic action (see the `session-lifecycle` capability)
- **AND** if the effective `pause_restores_ownerships_on_resume` is `True`, every active `TeamTowerOwnership` and `TeamZoneOwnership` SHALL be closed with `timestamp_end = window.started_at` and recorded on the window
- **AND** if the effective `pause_restores_ownerships_on_resume` is `False`, those ownerships SHALL still be closed the same way but SHALL NOT be recorded for restore
- **AND** calling `pause` on a Session that is not `RUNNING` SHALL be rejected with HTTP 409

#### Scenario: Resuming restores ownerships

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/resume/` and the effective `pause_restores_ownerships_on_resume` is `True`
- **THEN** the system SHALL transition the Session from `PAUSED` to `RUNNING` and close the newest open `PauseWindow` in one atomic action
- **AND** open a new ownership row for every `(team, tower)` and `(team, zone)` pair that was open at pause time, with `timestamp_start = resume_time`

#### Scenario: Resuming without restore

- **WHEN** a Session is resumed and the effective `pause_restores_ownerships_on_resume` is `False`
- **THEN** the system SHALL transition it from `PAUSED` to `RUNNING` and close the open window without reopening ownerships; teams must re-capture after resume

### Requirement: Pause all sessions of a game

The system SHALL let staff pause every active Session of a Game in one call, driving each through the same pause transition.

#### Scenario: Bulk pause

- **WHEN** a staff user calls `POST /api/staff/games/{id}/pause_all/`
- **THEN** the system SHALL open a `PauseWindow` on every `RUNNING` Session of that Game in a single call
- **AND** each affected Session SHALL land in `PAUSED` so its explicit state and its open window stay equivalent (see the `session-lifecycle` capability)
