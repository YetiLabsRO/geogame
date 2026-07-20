## ADDED Requirements

### Requirement: ASGI real-time transport

The system SHALL run under a Django Channels ASGI application that serves websocket connections for live game updates, backed by a Redis channel layer for cross-process fan-out, while keeping the WSGI/HTTP path working for deployments that do not enable real-time.

#### Scenario: Serving websockets under ASGI

- **WHEN** the project is served under its ASGI application
- **THEN** the system SHALL route HTTP requests to the existing Django application and websocket connections to a Channels URL router
- **AND** it SHALL use a Redis-backed channel layer so a broadcast from any worker process reaches connected clients on every process
- **AND** an in-memory channel layer MAY be used for tests and single-process development

#### Scenario: Real-time disabled or channel layer unavailable

- **WHEN** a Session's effective `realtime_enabled` is false, or the channel layer is unavailable
- **THEN** the system SHALL NOT require a websocket for correct operation
- **AND** clients SHALL fall back to the REST polling/refresh path (see the `player-app` and `staff-app` capabilities) with no loss of correctness

### Requirement: Session-scoped authenticated websocket

The system SHALL expose a token-authenticated websocket endpoint that admits a caller only to the group for a Session they belong to, so real-time events never leak across Sessions.

#### Scenario: Authenticated member connects

- **WHEN** a client opens the websocket for a Session presenting a valid DRF token
- **AND** the user has an active membership on that Session, or is staff
- **THEN** the system SHALL accept the connection and join the client to the `session.<id>` group
- **AND** on disconnect it SHALL remove the client from that group

#### Scenario: Unauthorized socket rejected

- **WHEN** a client opens the websocket without a valid token, or for a Session on which it has no active membership and is not staff
- **THEN** the system SHALL reject the connection
- **AND** it SHALL NOT deliver any Session events to that client

#### Scenario: Events stay within their Session

- **WHEN** the system broadcasts an event to the `session.A` group
- **THEN** clients connected only to Session B SHALL NOT receive that event

### Requirement: Live map recolor broadcast

The system SHALL broadcast tower ownership changes and zone control changes to a Session's group so every connected client recolors the affected tower or zone in real time.

#### Scenario: Tower conquered or stolen

- **WHEN** a team conquers or steals a tower and ownership is recomputed
- **THEN** the system SHALL broadcast a `tower.ownership_changed` event to the Session group carrying the affected tower and its new per-TeamGroup coloring
- **AND** connected clients SHALL recolor that tower on the map without a full reload
- **AND** if the change flips zone control the system SHALL also broadcast a `zone.control_changed` event so clients recolor the zone

#### Scenario: Client reconciles on reconnect

- **WHEN** a client (re)connects to the websocket after a drop
- **THEN** it SHALL first fetch a fresh REST snapshot of zones/towers and reconcile it before applying subsequent live events, so a missed event never leaves the map stale

### Requirement: Live scoreboard broadcast

The system SHALL broadcast every team's current totals to a Session's group so players and staff see standings update in real time and can tell when a team is being overtaken.

#### Scenario: Totals change

- **WHEN** a team's locked or floating score changes
- **THEN** the system SHALL broadcast a `scoreboard.updated` event carrying each team's locked plus floating totals for the Session
- **AND** connected clients SHALL update the live scoreboard from that event
- **AND** the system SHALL throttle or coalesce these broadcasts to at most once per short window per Session to avoid storms during rapid captures

### Requirement: Bonus pop-up broadcast

The system SHALL broadcast bonus / score-multiplier appearances to a Session's group so clients can surface them the moment they occur.

#### Scenario: A bonus appears

- **WHEN** a score multiplier or bonus becomes active for a Session (see the `score-multipliers` capability)
- **THEN** the system SHALL broadcast a `bonus.appeared` event to the Session group describing the bonus and where it applies
- **AND** connected clients SHALL surface it live

### Requirement: Typed real-time event envelope

The system SHALL send every real-time message using a single typed envelope so clients can dispatch on event type against a stable, versionable contract.

#### Scenario: Event structure

- **WHEN** the system emits any real-time event
- **THEN** the message SHALL be an envelope `{ type, session, ts, payload }` where `type` is one of `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated`, or `bonus.appeared`
- **AND** `session` SHALL identify the originating Session and `ts` SHALL be an ISO-8601 timestamp
- **AND** clients SHALL ignore envelopes whose `type` they do not recognize
