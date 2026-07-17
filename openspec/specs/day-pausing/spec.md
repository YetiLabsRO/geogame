# day-pausing Specification

## Purpose
TBD - created by archiving change day-pausing-and-failure-consequences. Update Purpose after archive.
## Requirements
### Requirement: Pause window model

The system SHALL model day cut-off pauses as `game.PauseWindow` records so a Session can be paused and resumed any number of times over its lifetime.

#### Scenario: A session is paused iff it has an open window

- **WHEN** the system evaluates whether a Session is paused
- **THEN** the Session SHALL be considered paused if and only if it has a `PauseWindow` with `ended_at IS NULL`
- **AND** a `PauseWindow` SHALL record `session`, `started_at`, a nullable `ended_at`, and the snapshots needed to restore ownerships on resume
- **AND** the `PauseWindow` model SHALL live in the `game` app alongside the ownership records it interacts with

### Requirement: Pause behavior configuration

The system SHALL expose pause-behavior knobs on `Game` as defaults, each overridable per `Session`.

#### Scenario: Default knob values

- **WHEN** a Game is created
- **THEN** it SHALL default `pause_freezes_floating_score` to `True`, `pause_restores_ownerships_on_resume` to `True`, and `pause_rejects_submissions` to `True`

#### Scenario: Per-session override wins

- **WHEN** a Session sets an override for a pause knob
- **THEN** the effective value for that Session SHALL be the Session override, otherwise the Game default

### Requirement: Pause and resume endpoints

The system SHALL let staff open and close pause windows for a Session, closing and (optionally) restoring ownerships.

#### Scenario: Pausing closes and records ownerships

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/pause/`
- **THEN** the system SHALL open a `PauseWindow`
- **AND** if the effective `pause_restores_ownerships_on_resume` is `True`, every active `TeamTowerOwnership` and `TeamZoneOwnership` SHALL be closed with `timestamp_end = window.started_at` and recorded on the window
- **AND** if the effective `pause_restores_ownerships_on_resume` is `False`, those ownerships SHALL still be closed the same way but SHALL NOT be recorded for restore

#### Scenario: Resuming restores ownerships

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/resume/` and the effective `pause_restores_ownerships_on_resume` is `True`
- **THEN** the system SHALL close the newest open `PauseWindow`
- **AND** open a new ownership row for every `(team, tower)` and `(team, zone)` pair that was open at pause time, with `timestamp_start = resume_time`

#### Scenario: Resuming without restore

- **WHEN** a Session is resumed and the effective `pause_restores_ownerships_on_resume` is `False`
- **THEN** the system SHALL close the open window without reopening ownerships; teams must re-capture after resume

### Requirement: Pause all sessions of a game

The system SHALL let staff pause every active Session of a Game in one call.

#### Scenario: Bulk pause

- **WHEN** a staff user calls `POST /api/staff/games/{id}/pause_all/`
- **THEN** the system SHALL open a `PauseWindow` on every active Session of that Game in a single call

### Requirement: Pause-aware floating score

The system SHALL suspend floating-score accrual across a pause when configured to do so.

#### Scenario: Frozen score during a pause

- **WHEN** a Session is paused and the effective `pause_freezes_floating_score` is `True`
- **THEN** each open zone ownership SHALL be closed at `window.started_at` and the floating it earned up to that instant SHALL be locked into `Team.score`
- **AND** `Team.current_score()` SHALL stay stable for the duration of the window (no accrual while paused), evaluating as of `window.started_at`

#### Scenario: Not freezing

- **WHEN** a Session is paused and the effective `pause_freezes_floating_score` is `False`
- **THEN** zone ownerships SHALL still be closed at `window.started_at`, but the in-progress floating for the current window SHALL NOT be credited to `Team.score`

### Requirement: Submissions while paused

The system SHALL define submission behavior while a Session is paused according to configuration.

#### Scenario: Rejecting submissions while paused

- **WHEN** a challenge submission is made while a Session is paused and the effective `pause_rejects_submissions` is `True`
- **THEN** the system SHALL reject it with HTTP 409

#### Scenario: Holding submissions while paused

- **WHEN** a challenge submission is made while a Session is paused and the effective `pause_rejects_submissions` is `False`
- **THEN** the system SHALL accept it and store it as `PENDING`, but SHALL NOT trigger capture until the Session resumes

### Requirement: Pauses are staff-triggered only

The system SHALL only pause or resume a Session in response to an explicit staff action.

#### Scenario: No automatic pausing

- **WHEN** a day cut-off or any time-based event occurs
- **THEN** the system SHALL NOT automatically or on a schedule pause or resume a Session in this phase

