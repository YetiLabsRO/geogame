## ADDED Requirements

### Requirement: Trail game mode

The system SHALL support a `TRAIL` game mode, distinct from `DOMINATION`, selectable on a Game and resolved per Session by the effective-value config pattern, so that a trail-mode run uses clue-driven point-to-point progression instead of zone/floating-point control.

#### Scenario: Selecting the mode on a Game

- **WHEN** a creator sets a Game's `mode`
- **THEN** the system SHALL accept `DOMINATION` (the default, preserving all current behaviour) or `TRAIL`
- **AND** a Session SHALL carry a nullable `mode` override so `effective_mode(session)` resolves to the Session override when set, otherwise the Game default

#### Scenario: Trail mode replaces domination scoring

- **WHEN** `effective_mode(session)` is `TRAIL`
- **THEN** the Session SHALL run the trail loop and SHALL NOT accrue zone or floating-point scoring (the `scoring` capability is inert for that Session)
- **AND** a Session whose `effective_mode` is `DOMINATION` SHALL expose no trail state and SHALL behave exactly as before this change

### Requirement: Trail structure over repository points

The system SHALL model a trail as `game.Trail` (one per trail-mode Game) composed of `game.TrailStep` nodes bound to repository Towers and `game.TrailEdge` clue links, supporting fixed-order, branching-graph, and circuit structures over the same steps.

#### Scenario: Defining the trail and its steps

- **WHEN** a creator authors a Trail on a trail-mode Game
- **THEN** the Trail SHALL carry a `structure` of `FIXED_ORDER`, `GRAPH`, or `CIRCUIT`
- **AND** each `TrailStep` SHALL bind to a repository `Tower` that resolves through the Game's Collections, and SHALL carry an `order`, an `is_start` flag, an `is_finish` flag, an optional `gate_challenge`, and clue content

#### Scenario: Fixed order runs a straight line

- **WHEN** a Trail's `structure` is `FIXED_ORDER`
- **THEN** the system SHALL advance a party through steps strictly by ascending `order` (1→2→3→4)
- **AND** the next step SHALL be derived from `order` without requiring explicit edges

#### Scenario: Graph edges enable branches

- **WHEN** a Trail's `structure` is `GRAPH`
- **THEN** a `TrailEdge` SHALL be a directed link from one `TrailStep` to another carrying the clue that points toward its target
- **AND** a step with two or more outgoing edges SHALL present a branch, so the party chooses which revealed clue to follow (see the "Branching choice" requirement)

### Requirement: Circuit with per-party start offset

The system SHALL support a `CIRCUIT` structure in which every party runs the same cyclic order of steps but each party starts at a different step and follows the order from its own start, wrapping around to the point before its start.

#### Scenario: Two parties start at different points on one loop

- **WHEN** a Trail's `structure` is `CIRCUIT` and two teams are assigned different `start_step`s
- **THEN** each team SHALL traverse the shared cyclic order beginning at its own `start_step`
- **AND** each team's route SHALL wrap around the loop and finish at the step immediately preceding its start, so the teams are spread around the circuit rather than colliding

### Requirement: Variable starting knowledge

The system SHALL let a Trail configure how much of the map a party knows at the start, as `ALL_KNOWN`, `ONE_KNOWN`, or `NONE_KNOWN`, seeding each party's initial reveal accordingly.

#### Scenario: All points known

- **WHEN** a Trail's `starting_knowledge` is `ALL_KNOWN`
- **THEN** every step's point SHALL be revealed to the party from the start
- **AND** the party MAY see all points yet SHALL still be required to progress in the trail's structural order via geofencing and gates

#### Scenario: Only the start known

- **WHEN** a Trail's `starting_knowledge` is `ONE_KNOWN`
- **THEN** only the party's start step SHALL be revealed initially
- **AND** each subsequent point SHALL be revealed only when the preceding step's gate is unlocked

#### Scenario: No point known — discover the start

- **WHEN** a Trail's `starting_knowledge` is `NONE_KNOWN`
- **THEN** no step's point SHALL be revealed initially and the party SHALL have to discover the start (for example from an out-of-band `start_hint`) before any progression
- **AND** staff SHALL be able to invoke a "reveal start" override for a party that cannot find the start

### Requirement: Geofenced step arrival

The system SHALL require a party to be physically at a step's Tower before that step can be advanced, reusing the proximity check of the `challenge-submission` capability.

#### Scenario: Arriving within range

- **WHEN** a member of the party submits from within the effective `proximity_meters` of a revealed step's Tower
- **THEN** the system SHALL record the step as `ARRIVED` for that party
- **AND** a submission farther than `proximity_meters` from the step's Tower SHALL be rejected, exactly as for domination submissions

### Requirement: Clue unlock gate

The system SHALL gate progression at each step behind an unlock action — answering a question, reading and acknowledging a clue, or submitting a team photo — modelled as the step's `gate_challenge` and validated through the `challenge-types` capability, revealing the next step(s) and clue(s) only on success.

#### Scenario: Completing a question or photo gate

- **WHEN** a party at an `ARRIVED` step completes its `gate_challenge` and the submission is validated per its challenge type (see the `challenge-types` capability)
- **THEN** the system SHALL mark the step `UNLOCKED` for that party
- **AND** the system SHALL reveal the next step(s) and their clue(s) to that party

#### Scenario: Read-only gate auto-advances on arrival

- **WHEN** a step has no `gate_challenge` (a read-only "acknowledge the clue" gate)
- **THEN** arrival within range SHALL unlock the step immediately
- **AND** the next step(s) and clue(s) SHALL be revealed without a further submission

### Requirement: Branching choice

The system SHALL, at a step with multiple outgoing edges in a `GRAPH` trail, reveal every outgoing clue and let the party choose which next point to travel to.

#### Scenario: Party picks a branch

- **WHEN** a party unlocks a step that has two or more outgoing `TrailEdge`s
- **THEN** the system SHALL reveal all of that step's outgoing clues and their target points as available next steps
- **AND** the party MAY travel to any one of them, and unlocking the chosen target SHALL continue the trail from there

### Requirement: Per-team route assignment

The system SHALL assign each team (or solo player) its own start and, for `FIXED_ORDER` and `CIRCUIT` trails, its own ordered sequence of steps via `game.TeamTrailRoute`, so competing parties walk different routes and do not converge on the same point.

#### Scenario: Different teams get different routes

- **WHEN** a runner assigns routes for a `FIXED_ORDER` trail
- **THEN** the system SHALL let each team receive a distinct ordered sequence of steps (for example team A gets 1-2-3-4 while team B gets 1-3-2-4-7)
- **AND** each team's progression SHALL follow its own assigned sequence rather than a single global order

#### Scenario: Graph route pins only the start

- **WHEN** a team is assigned a route on a `GRAPH` trail
- **THEN** the route SHALL pin only the `start_step`
- **AND** the team's path SHALL emerge from the branch choices it makes at each step

### Requirement: Single-player or multi-team participation

The system SHALL support both single-player and multi-team trail runs via a Trail `participation` of `SOLO` or `TEAM`, binding routes and progress to the correct subject.

#### Scenario: Solo run

- **WHEN** a Trail's `participation` is `SOLO`
- **THEN** the system SHALL bind route assignment and progress to an individual player rather than a team
- **AND** when `participation` is `TEAM` the same records SHALL bind to the team, and a team member's arrival or unlock SHALL count for the whole team

### Requirement: Per-team progress and reveal tracking

The system SHALL track each party's trail progress in `game.TeamTrailProgress`, scoped to `(session, team)`, driving per-party point reveal through the `tower-visibility` capability so a party sees only points it has unlocked, with no leakage across parties.

#### Scenario: Progress states advance per party

- **WHEN** a party interacts with a step
- **THEN** the system SHALL record its state as `REVEALED`, `ARRIVED`, or `UNLOCKED` with the corresponding timestamps, for that `(session, team)` only
- **AND** an unrevealed trail point SHALL remain hidden on that party's map via the `tower-visibility` capability

#### Scenario: No cross-party leakage

- **WHEN** one party reveals or unlocks a step
- **THEN** the reveal SHALL apply only to that party
- **AND** another party's revealed set and current position SHALL be unaffected

### Requirement: Trail completion and ranking

The system SHALL mark a party finished when it reaches its finish step (or has visited all required steps) and SHALL rank parties for the Session by progression and time, as trail-mode scoring distinct from domination floating points.

#### Scenario: Finishing the trail

- **WHEN** a party unlocks its finish step (or the last required step)
- **THEN** the system SHALL mark the party finished and record its finish time
- **AND** the Session SHALL rank parties by steps unlocked descending, then finish time ascending

### Requirement: Trail APIs

The system SHALL expose staff/creator authoring APIs for trails, steps, edges, and route assignment, and player APIs for the party's current trail state and branch options, with arrival and gate unlock riding the existing challenge submission endpoint.

#### Scenario: Authoring a trail

- **WHEN** a creator calls the staff trail APIs
- **THEN** the system SHALL provide `/api/staff/trails/`, `/api/staff/trail-steps/`, `/api/staff/trail-edges/`, and per-session `/api/staff/sessions/{id}/trail-routes/` to define structure, steps, clues, and per-team routes
- **AND** saving a Trail SHALL validate that every non-start step is reachable, at least one finish is reachable, and every step's Tower resolves through the Game's Collections

#### Scenario: Playing the trail

- **WHEN** a player calls `GET /api/trail/state/`
- **THEN** the system SHALL return the party's current position, its revealed steps, the active clue(s), and its progress
- **AND** `GET /api/trail/next/` SHALL return the available next step(s) at the current position, while arrival and gate unlock SHALL flow through the existing `POST /api/team_tower_challenges/` submission endpoint
