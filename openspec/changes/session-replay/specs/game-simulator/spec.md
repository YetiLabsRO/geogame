## ADDED Requirements

### Requirement: Staff-driven game simulator

The system SHALL provide a staff-only simulator that runs a fake game against a real Game and Session, so game designs can be exercised without gathering people in a field.

#### Scenario: Simulator access

- **WHEN** a non-staff user calls any simulator endpoint
- **THEN** the system SHALL deny the request
- **AND** no simulator surface SHALL be exposed in the player app

#### Scenario: Nothing runs unattended

- **WHEN** a simulation run exists
- **THEN** the system SHALL advance it only in response to an explicit staff action
- **AND** no background process SHALL step, finish, or delete a run on its own

### Requirement: Simulation drives real domain code

The system SHALL exercise the same domain services and models the live API uses, and SHALL NOT implement a parallel copy of game rules.

#### Scenario: Driving the engine

- **WHEN** a simulation performs player movement, discovery, proximity, tower capture, or a lifecycle change
- **THEN** it SHALL do so through the same models and services the live API calls — location pings and discovery evaluation, proximity reports and the dementors tick, team-tower challenge confirmation and tower assignment, and Session lifecycle transitions
- **AND** a rule change in those services SHALL take effect in simulation without a corresponding change in the simulator

#### Scenario: No self-calls

- **WHEN** the simulator drives the game
- **THEN** it SHALL call domain code in-process rather than issuing HTTP requests to its own API

### Requirement: Simulation runs are configurable

The system SHALL let staff configure a run before it starts.

#### Scenario: Configuring a run

- **WHEN** a staff user creates a simulation run
- **THEN** they SHALL be able to set the run name, an optional template Game to clone, the game mode, player count, team count, tick duration, capture probability, movement step, spawn centre and radius, and proximity thresholds
- **AND** unspecified settings SHALL fall back to documented defaults

#### Scenario: Cloning a template game

- **WHEN** a run names a template Game
- **THEN** the run SHALL exercise that Game's towers, zones, and challenge bank
- **AND** when no template is given the run SHALL create a bare Game, which has no towers to capture

#### Scenario: Setup failure leaves nothing behind

- **WHEN** setting up a run fails
- **THEN** the system SHALL report the failure
- **AND** SHALL leave no partially-created run, Game, Session, or fake user behind

### Requirement: Simulation runs are deterministic

The system SHALL make a run reproducible from its seed and configuration.

#### Scenario: Replaying a seed

- **WHEN** two runs share a seed and configuration and are stepped the same number of ticks
- **THEN** they SHALL produce the same sequence of simulated decisions

#### Scenario: Ticks are not carbon copies

- **WHEN** a run is stepped repeatedly
- **THEN** successive ticks SHALL differ from one another rather than repeating one tick's random draws

### Requirement: Simulation run lifecycle

The system SHALL expose a run's lifecycle as explicit staff actions and SHALL reject actions the run's state does not allow.

#### Scenario: Stepping a run

- **WHEN** a staff user steps a run by a number of ticks
- **THEN** the system SHALL advance it exactly that many ticks synchronously
- **AND** SHALL return the resulting state snapshot

#### Scenario: Pausing and stopping

- **WHEN** a staff user pauses or stops a run
- **THEN** the system SHALL transition the run's Session accordingly
- **AND** stopping SHALL close ownership records while retaining the Session's history

#### Scenario: An action the state forbids

- **WHEN** a staff user requests an action the run's current state does not allow
- **THEN** the system SHALL reject it as a conflict rather than partially applying it

### Requirement: Every simulated action is recorded

The system SHALL record each action a run takes on an append-only tape, so a run can be replayed after the fact.

#### Scenario: Recording actions

- **WHEN** a run spawns players, moves them, evaluates proximity, captures a tower, or transitions its Session
- **THEN** the system SHALL append an event carrying the tick, the acting player where one applies, the action, its inputs, and its outcome
- **AND** events SHALL never be modified or deleted while the run exists

#### Scenario: Reading the tape

- **WHEN** a staff user requests a run's timeline
- **THEN** the system SHALL return the full tape in tick order
- **AND** the tape SHALL be sufficient to reconstruct the run as replay frames (see the `session-replay` capability)

### Requirement: Simulations are non-invasive and fully removable

The system SHALL keep simulated data distinguishable from real data and SHALL remove every trace of a run on teardown.

#### Scenario: Simulated rows are identifiable

- **WHEN** a run creates a Game, Session, and roster
- **THEN** they SHALL be identifiable as simulated
- **AND** tracking them SHALL require no simulation-specific fields on the core game and roster models

#### Scenario: Tearing down a run

- **WHEN** a staff user deletes a simulation run
- **THEN** the system SHALL delete every row the run created — its Game and Session and everything they own, its fake users and their profiles, and its event tape
- **AND** no real Game, Session, or user SHALL be affected
