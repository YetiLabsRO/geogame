## ADDED Requirements

### Requirement: Score multiplier model

The system SHALL model `game.ScoreMultiplier` as a factor applied to a tower, a zone, or the whole game, carrying a spatial scope, a decimal factor, a type, a window, and an active flag.

#### Scenario: Defining a multiplier

- **WHEN** an organiser creates a `ScoreMultiplier`
- **THEN** it SHALL have a `scope` of `TOWER`, `ZONE`, or `GLOBAL`, a decimal `factor` greater than `0`, a `type` of `MANUAL`, `SCHEDULED`, or `RANDOM_BONUS`, an `is_active` flag, an optional window, and an optional player-facing `label`
- **AND** a `TOWER`-scoped multiplier SHALL reference exactly one `tower`, a `ZONE`-scoped one exactly one `zone`, and a `GLOBAL`-scoped one neither
- **AND** it SHALL be owned by exactly one of a `Game` (applying to every Session of that game) or a single `Session` (applying to that run only)

#### Scenario: Rejecting an invalid multiplier

- **WHEN** a multiplier is saved with a non-positive `factor`, with neither or both of `game`/`session` set, or with a `scope` whose required `tower`/`zone` reference is missing or mismatched
- **THEN** the system SHALL reject it with a validation error
- **AND** it SHALL NOT affect any scoring

### Requirement: Effective factor resolution

The system SHALL resolve the effective factor for a target tower or zone in a Session at a given time as the product of the factors of every in-effect multiplier whose scope matches, defaulting to `1.0` when none apply.

#### Scenario: Composing multiple in-effect multipliers

- **WHEN** the effective factor for a tower is resolved at time `T`
- **THEN** the system SHALL multiply the `factor` of every in-effect multiplier that is `GLOBAL`-scoped or `TOWER`-scoped to that tower, drawn from the union of the Session's own multipliers and its Game's multipliers
- **AND** a `GLOBAL 2×` in effect together with a `TOWER 2×` on that tower SHALL yield an effective factor of `4.0`
- **AND** the same rule SHALL apply to a zone using `GLOBAL`-scoped and `ZONE`-scoped multipliers

#### Scenario: No multiplier applies

- **WHEN** no in-effect multiplier matches a target
- **THEN** the resolved effective factor SHALL be `1.0`
- **AND** scoring for that target SHALL be identical to the pre-multiplier behaviour (see the `scoring` capability)

### Requirement: Multiplier windows and active state

The system SHALL treat a multiplier as in effect at a time only when it is active and that time falls within its resolved window.

#### Scenario: A scheduled window relative to session start

- **WHEN** a `SCHEDULED` multiplier has a `window_start_offset` of 1 hour and a `window_end_offset` of 2 hours
- **THEN** it SHALL be in effect only for a Session between one and two hours after that Session's `start`
- **AND** the same template multiplier SHALL replay on every Session of its Game regardless of wall-clock date

#### Scenario: A manual live toggle

- **WHEN** an admin activates a `MANUAL` multiplier and later deactivates it
- **THEN** it SHALL be in effect only while `is_active` is true
- **AND** toggling it SHALL affect only worth accrued from the toggle instant forward and SHALL NOT retroactively rewrite already-finalized locked score

#### Scenario: A random bonus with an absolute window

- **WHEN** a `RANDOM_BONUS` multiplier is created with an absolute `starts_at`/`ends_at` window
- **THEN** it SHALL be in effect only between those instants
- **AND** an unset window bound SHALL be treated as open on that side

### Requirement: Authoring scheduled multipliers

The system SHALL let a creator author `SCHEDULED` (and other `Game`-owned) multipliers on a Game template over a staff/creator REST API.

#### Scenario: Managing template multipliers

- **WHEN** a creator calls `GET/POST/PATCH/DELETE /api/staff/games/{id}/score-multipliers/`
- **THEN** the system SHALL let them list, create, edit, and delete that Game's multipliers
- **AND** those multipliers SHALL apply to every Session launched from that Game

#### Scenario: Carrying multipliers through a clone

- **WHEN** a Game is cloned (see the `game-authoring-roles` capability)
- **THEN** the clone SHALL deep-copy the original's `Game`-owned multipliers
- **AND** it SHALL NOT copy any `Session`-owned multipliers

### Requirement: Live multiplier control

The system SHALL let a runner create and toggle live `MANUAL` and `RANDOM_BONUS` multipliers on a running Session over a staff REST API.

#### Scenario: Dropping a live bonus

- **WHEN** a runner calls `POST /api/staff/sessions/{id}/score-multipliers/` with a scope, target, `factor`, optional absolute window, and `label`
- **THEN** the system SHALL create a `Session`-owned multiplier affecting only that Session
- **AND** `POST .../score-multipliers/{id}/activate/` and `.../deactivate/` SHALL toggle a `MANUAL` multiplier's `is_active` live

### Requirement: Exposing active multipliers

The system SHALL expose the multipliers currently in effect for a Session so the map and scoreboard can announce them.

#### Scenario: Listing what is boosted right now

- **WHEN** a client calls `GET /api/.../sessions/{id}/score-multipliers/active/`
- **THEN** the system SHALL return each in-effect multiplier's `factor`, `scope`, target, and `label`
- **AND** the player app SHALL surface these read-only (e.g. "Double points now", "Bonus at Old Tower") without letting players change them

### Requirement: Applies across all game types

The system SHALL apply score multipliers as a scoring-layer feature to every game type, independent of mode.

#### Scenario: Same mechanism regardless of mode

- **WHEN** a Game of any type resolves a tower's or zone's worth
- **THEN** the effective-factor resolution SHALL be applied identically
- **AND** score multipliers SHALL NOT be gated to a particular game mode
