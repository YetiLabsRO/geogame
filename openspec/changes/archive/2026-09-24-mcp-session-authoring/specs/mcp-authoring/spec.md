## ADDED Requirements

### Requirement: Session read surface

The system SHALL provide read tools that return the creator's Sessions for a Game, including each Session's lifecycle state, time window, and which overridable config knobs are overridden versus inherited, so the LLM can target an existing Session without guessing its identity.

#### Scenario: Listing a game's sessions

- **WHEN** the LLM calls `list_sessions`, optionally filtered by Game
- **THEN** the server SHALL return the Sessions of the Games the connected creator is permitted to author, each with its `slug`, `name`, `state`, `start_time`, `end_time`, and `scheduled_start`
- **AND** the result SHALL exclude Sessions of Games outside that creator's authoring scope

#### Scenario: Distinguishing an override from an inherited default

- **WHEN** the LLM calls `get_session` for a Session it may author
- **THEN** the server SHALL return, for each overridable config knob, both the Session's own override (or null when unset) and the effective value resolved against the Game default
- **AND** the LLM SHALL thereby be able to propose only knobs that actually differ from what the Session already resolves to

#### Scenario: Session config staging becomes reachable

- **WHEN** the LLM has obtained a Session identifier from a session read tool
- **THEN** it SHALL be able to stage a config override for that Session via the existing session-scoped config tool
- **AND** the staged override SHALL be validated against the config schema exactly as a Game-scoped override is

### Requirement: Staging a session

The system SHALL provide a `propose_session` tool that stages the creation of a Session under a Game — one that already exists or one proposed in the same proposal — so an approved proposal yields a runnable Session rather than only a Game template.

#### Scenario: Staging a session under an existing game

- **WHEN** the LLM calls `propose_session` with a Game reference, a `name`, a `slug`, a `start_time`, an `end_time`, and an optional `scheduled_start`
- **THEN** the server SHALL append a Session `ProposedOperation` to the caller's open `AuthoringProposal` with the rationale attached
- **AND** no real Session SHALL exist until the proposal is approved and applied

#### Scenario: Staging a session under a proposed game

- **WHEN** the LLM proposes a Session whose Game is itself proposed in the same proposal
- **THEN** the Session operation SHALL reference the Game by a temp ref
- **AND** the apply engine SHALL resolve that temp ref to the created Game's real primary key before creating the Session

#### Scenario: A staged session is validated as the staff API would

- **WHEN** an approved Session operation is applied
- **THEN** its payload SHALL be validated through the same serializer the staff session API uses
- **AND** an invalid time window or a slug colliding with an existing Session of that Game SHALL fail the operation with the error recorded, rather than creating a malformed Session

### Requirement: Staged sessions are created in DRAFT

The system SHALL create every applied Session in the `DRAFT` lifecycle state, and SHALL NOT accept a lifecycle state as a staged value.

#### Scenario: An applied session lands in DRAFT

- **WHEN** an approved Session operation is applied
- **THEN** the created Session's state SHALL be `DRAFT`
- **AND** a human SHALL move it onward through the normal lifecycle actions

#### Scenario: A proposed state is refused

- **WHEN** the LLM includes a lifecycle state in a `propose_session` payload
- **THEN** the system SHALL NOT write that state
- **AND** the Session SHALL still be created in `DRAFT`

### Requirement: Lifecycle transitions are outside the authoring surface

The system SHALL keep Session lifecycle transitions — opening participation, starting, pausing, resuming, and finishing — off the MCP authoring path entirely, because they are live operational acts affecting players mid-game.

#### Scenario: No transition tool is published

- **WHEN** an LLM client enumerates the authoring tools
- **THEN** the advertised tools SHALL contain no tool that performs or stages a Session lifecycle transition

#### Scenario: A transition cannot be staged as an operation

- **WHEN** an operation is staged that would set or advance a Session's lifecycle state
- **THEN** the system SHALL refuse it
- **AND** the apply engine SHALL NOT perform any lifecycle transition on any Session

### Requirement: Staging a team

The system SHALL provide a `propose_team` tool that stages the creation of a Team under a Session — existing or proposed in the same proposal — so an approved Session arrives with the roster shells that will play it.

#### Scenario: Staging a team under a proposed session

- **WHEN** the LLM calls `propose_team` with a Session reference, a `name`, a `color`, an optional `description`, and an optional TeamGroup reference
- **THEN** the server SHALL append a Team `ProposedOperation` referencing the Session by real primary key or temp ref
- **AND** the apply engine SHALL resolve a Game → Session → Team temp-ref chain in dependency order

#### Scenario: A staged team is created empty

- **WHEN** an approved Team operation is applied
- **THEN** the created Team SHALL have no members
- **AND** its rendering in the review surface SHALL identify it as a shell that players join through invites or a join code

### Requirement: Player membership is never staged or applied

The system SHALL NOT expose any tool that adds, removes, or asserts a person's membership of a Team, and the apply engine SHALL NOT write team membership records, because assigning real people to teams is not an authoring decision an LLM may make.

#### Scenario: No membership tool is published

- **WHEN** an LLM client enumerates the authoring tools
- **THEN** the advertised tools SHALL contain no tool that writes team membership

#### Scenario: Membership in a payload is refused

- **WHEN** a staged Team payload carries member, player, or user references
- **THEN** the system SHALL refuse to stage the operation
- **AND** SHALL record the refusal in the audit trail

### Requirement: Session-scoped authorization follows the game

The system SHALL scope every Session and Team read, stage, and apply to whether the connected creator may edit the owning Game, re-checking at apply time as it does for every other entity.

#### Scenario: Out-of-scope session work is refused

- **WHEN** the LLM stages a Session or Team operation whose owning Game the creator may not edit
- **THEN** the server SHALL refuse to stage it and SHALL record the refusal in the audit trail

#### Scenario: Authorization is re-checked at apply time

- **WHEN** an approved Session or Team operation is applied and the creator is no longer permitted to edit the owning Game
- **THEN** the apply engine SHALL fail that operation rather than apply it

## MODIFIED Requirements

### Requirement: Read surface over available game elements

The system SHALL provide read/discovery tools that return the creator's available Collections, Towers, Zones, Challenges, Games (templates), Sessions, TeamGroups, and per-game roles, so the LLM composes new games only from valid existing options.

#### Scenario: Listing available elements

- **WHEN** the LLM calls a read tool such as `list_collections`, `list_towers`, `list_challenges`, `list_games`, `list_sessions`, `list_team_groups`, or `list_game_roles`
- **THEN** the server SHALL return the elements the connected creator is permitted to author, serialized through the same shapes as the staff/creator REST API
- **AND** the result SHALL exclude elements outside that creator's authoring scope

#### Scenario: Reading is safe and audited

- **WHEN** a read tool is invoked
- **THEN** it SHALL return data without staging or applying any change
- **AND** the invocation SHALL be recorded as an audit event

### Requirement: Configuration and role option discovery

The system SHALL provide a tool that describes the available configuration knobs — their names, value types, allowed enum values, defaults, and the scopes at which each may be set — so the LLM can set only valid options when proposing a game or a session.

#### Scenario: Describing the config schema

- **WHEN** the LLM calls the config-schema discovery tool
- **THEN** the server SHALL return the catalog of Game/Session config knobs with type, allowed values, and default for each (see the `game-configuration`, `scoring`, and related capabilities)
- **AND** each knob SHALL declare the scopes at which it may be set, `game` and `session` for an overridable knob
- **AND** the catalog SHALL be derived from live model/serializer field definitions so newly added knobs appear without hand maintenance

#### Scenario: A proposed config value is validated against the schema

- **WHEN** the LLM proposes a config value outside a knob's allowed range or enum
- **THEN** the staging tool SHALL reject the operation and report the valid options
- **AND** SHALL NOT stage an out-of-range value

#### Scenario: A knob is proposed at a scope it does not support

- **WHEN** the LLM stages a session-scoped override for a knob that is not overridable per Session
- **THEN** the staging tool SHALL reject the operation and report the scopes that knob supports
- **AND** SHALL NOT stage the override

### Requirement: Suggest-only write tools stage proposals

The system SHALL provide write-intent tools (`propose_collection`, `propose_tower`, `propose_zone`, `suggest_challenge`, `propose_game`, `propose_game_role`, `propose_session`, `propose_team`, `propose_config`, `propose_link`) that append operations to a staged proposal and never write to real models.

#### Scenario: Staging a proposed element

- **WHEN** the LLM calls a `propose_*` or `suggest_*` tool
- **THEN** the server SHALL append a `ProposedOperation` (entity type, action, target reference, payload, rationale) to the caller's open `AuthoringProposal`
- **AND** the real game tables SHALL remain unchanged
- **AND** the tool SHALL return the proposal and operation identifiers so the LLM can continue building on them

#### Scenario: Batching a draft into one reviewable unit

- **WHEN** the LLM stages several related operations against the same open proposal
- **THEN** the server SHALL group them under that single `AuthoringProposal` so the human reviews them together
