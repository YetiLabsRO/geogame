## ADDED Requirements

### Requirement: Session lifecycle states

The system SHALL model a Session's lifecycle as a `Session.state` field with exactly the values `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, and `FINISHED`, and treat `state` as the single source of truth for the lifecycle.

#### Scenario: State field values

- **WHEN** a Session is created
- **THEN** its `state` SHALL be one of `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, or `FINISHED`
- **AND** a newly created Session SHALL default to `DRAFT`
- **AND** the lifecycle SHALL be read from `state` rather than reconstructed from other fields

#### Scenario: Legacy active flag derives from state

- **WHEN** any consumer reads `Session.is_active`
- **THEN** the system SHALL derive it as `True` when `state` is `OPEN_FOR_PARTICIPANTS`, `RUNNING`, or `PAUSED`, and `False` when `state` is `DRAFT` or `FINISHED`
- **AND** `is_active` SHALL be a read-only derived property, not an independently writable column (see the `sessions` capability)

### Requirement: Allowed lifecycle transitions

The system SHALL permit only an enumerated set of state transitions, each driven by exactly one named runner/staff action, and SHALL apply each transition's effect atomically.

#### Scenario: The transition table

- **WHEN** the system evaluates the allowed lifecycle transitions
- **THEN** it SHALL permit exactly these `(from → to)` edges, each driven by the named action:
  - `DRAFT → OPEN_FOR_PARTICIPANTS` via `open_participation`
  - `OPEN_FOR_PARTICIPANTS → DRAFT` via `close_participation`
  - `OPEN_FOR_PARTICIPANTS → RUNNING` via `start`
  - `RUNNING → PAUSED` via `pause`
  - `PAUSED → RUNNING` via `resume`
  - `RUNNING → FINISHED` via `finish`
  - `PAUSED → FINISHED` via `finish`
- **AND** `RUNNING ⇄ PAUSED` and `DRAFT ⇄ OPEN_FOR_PARTICIPANTS` SHALL be the only reversible pairs
- **AND** `FINISHED` SHALL be terminal with no outbound transition

#### Scenario: Rejecting an illegal transition

- **WHEN** an action is requested that is not an allowed edge from the Session's current `state` (for example `start` on a `DRAFT` Session, or any action on a `FINISHED` Session)
- **THEN** the system SHALL reject it with HTTP 409 and leave the `state` unchanged

### Requirement: Opening participation before the game starts

The system SHALL provide an `OPEN_FOR_PARTICIPANTS` state, entered from `DRAFT` via `open_participation`, that opens a pre-start window during which rosters gather, and SHALL let staff re-close it via `close_participation`.

#### Scenario: Opening the participation window

- **WHEN** a staff user calls `open_participation` on a `DRAFT` Session
- **THEN** the system SHALL transition it to `OPEN_FOR_PARTICIPANTS`
- **AND** it SHALL open the window during which Teams and rosters may be created and joined **before** the Session reaches `RUNNING` (see the `teams-and-groups` capability)

#### Scenario: Participation window timing

- **WHEN** `open_participation` is called and the Session has a `scheduled_start`
- **THEN** the system SHALL permit opening the window no earlier than 7 days and no later than 1 hour before `scheduled_start`
- **AND** an out-of-window open SHALL require an explicit staff `override`, otherwise be rejected
- **AND** when `scheduled_start` is unset, the window MAY be opened at any time

#### Scenario: Re-closing the participation window

- **WHEN** a staff user calls `close_participation` on an `OPEN_FOR_PARTICIPANTS` Session
- **THEN** the system SHALL transition it back to `DRAFT`
- **AND** it SHALL retain any Teams already created, so re-opening resumes the same roster

### Requirement: Starting a session

The system SHALL start gameplay only by transitioning a Session from `OPEN_FOR_PARTICIPANTS` to `RUNNING` via the `start` action.

#### Scenario: Starting the clock

- **WHEN** a runner calls `start` on an `OPEN_FOR_PARTICIPANTS` Session
- **THEN** the system SHALL transition it to `RUNNING` and begin the Session clock
- **AND** it SHALL NOT permit a direct `DRAFT → RUNNING` transition, so every Session passes through `OPEN_FOR_PARTICIPANTS` and rosters are always creatable before start

### Requirement: Pausing integrates with the pause window

The system SHALL make `PAUSED` equivalent to holding an open `PauseWindow`, transitioning `RUNNING ⇄ PAUSED` and opening/closing the window atomically so the two representations never disagree.

#### Scenario: Pausing opens a window

- **WHEN** a staff user calls `pause` on a `RUNNING` Session
- **THEN** the system SHALL transition it to `PAUSED` and open a `PauseWindow` in one atomic action (see the `day-pausing` capability for the pause side effects)

#### Scenario: Resuming closes the window

- **WHEN** a staff user calls `resume` on a `PAUSED` Session
- **THEN** the system SHALL transition it to `RUNNING` and close the newest open `PauseWindow` in one atomic action

#### Scenario: Paused-state invariant

- **WHEN** the system evaluates a Session
- **THEN** `state == PAUSED` SHALL hold if and only if the Session has a `PauseWindow` with `ended_at IS NULL`
- **AND** `Session.is_paused()` SHALL return `state == PAUSED`

### Requirement: Finishing a session

The system SHALL finish a Session by transitioning it to the terminal `FINISHED` state from either `RUNNING` or `PAUSED`, closing all open ownerships and preserving history.

#### Scenario: Finishing from running

- **WHEN** a runner calls `finish` on a `RUNNING` Session
- **THEN** the system SHALL transition it to `FINISHED`
- **AND** it SHALL close every open `TeamTowerOwnership` and `TeamZoneOwnership` (the same semantics as `unassign_all`; see the `game-lifecycle` capability)
- **AND** it SHALL preserve all records so the Session remains visible in history (see the `session-history` capability)

#### Scenario: Finishing from paused

- **WHEN** a runner calls `finish` on a `PAUSED` Session
- **THEN** the system SHALL close the open `PauseWindow` without reopening ownerships, then close all remaining open ownerships, and transition to `FINISHED`

#### Scenario: Finished is terminal

- **WHEN** any lifecycle action is requested on a `FINISHED` Session
- **THEN** the system SHALL reject it with HTTP 409 and keep the Session `FINISHED`

### Requirement: Lifecycle transition API

The system SHALL expose each lifecycle transition as a staff/runner REST action and report the current state and the legal next actions.

#### Scenario: Driving a transition over the API

- **WHEN** a staff user calls `POST /api/staff/sessions/{id}/open_participation/`, `.../close_participation/`, `.../start/`, `.../resume/`, or `.../finish/` (with `pause`/`resume` also served by the `day-pausing` endpoints)
- **THEN** the system SHALL apply the corresponding transition if it is legal for the current `state`, otherwise return HTTP 409

#### Scenario: Reporting allowed transitions

- **WHEN** a client reads a Session over the staff API
- **THEN** the serialized Session SHALL expose its current `state` and an `allowed_transitions` list of the actions legal from that state, so the runner UI can show only valid controls
