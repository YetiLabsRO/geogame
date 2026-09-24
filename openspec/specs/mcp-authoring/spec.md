# MCP Authoring Specification

## Purpose

Define the Model Context Protocol (MCP) authoring server: a governed interface through which an LLM client reads the creator's available game elements and *stages* proposed content, never writing to real game data. Every staged change set passes a human approval gate before an apply engine commits it, and every tool call, decision, and apply outcome is audited. Covers the read surface, config discovery, suggest-only write tools, the staged change-set model with temp references, creator-scoped authentication, the approve-then-apply lifecycle, the audit trail, and the staff review surface.

## Requirements

### Requirement: MCP authoring server

The system SHALL expose a Model Context Protocol (MCP) server that publishes tools for reading and proposing game content, so an LLM client can author games through a governed interface rather than by writing to the database directly.

#### Scenario: Connecting an LLM client

- **WHEN** an LLM client connects to the MCP authoring endpoint with a valid credential
- **THEN** the server SHALL complete the MCP handshake and advertise its read/discovery and suggest/stage tools
- **AND** it SHALL bind the connection to exactly one creator user for the lifetime of the session
- **AND** it SHALL open or attach an `AuthoringSession` recording the client name and the LLM model id when the host provides them

#### Scenario: No live-write path exists

- **WHEN** any write-intent tool is invoked over MCP
- **THEN** the tool SHALL only append a staged operation and SHALL NOT create or modify any real Collection, Tower, Zone, Challenge, Game, role, or config value
- **AND** the only code path that mutates real game data SHALL be the apply engine, reachable only after a human approval

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

### Requirement: LLM suggests challenge ideas from town context

The system SHALL let the LLM take the information it holds about a town and stage suggested Challenges, each carrying a rationale, so a creator receives a reviewable draft Challenge bank.

#### Scenario: Suggesting challenges

- **WHEN** the LLM calls `suggest_challenge` with proposed text, a difficulty, a tower-specific or generic binding, and a target Game
- **THEN** the server SHALL stage each suggestion as a proposed Challenge operation with the LLM's `rationale` attached
- **AND** it SHALL accept several suggestions in one call, staging each as its own operation
- **AND** none of the suggested Challenges SHALL exist as real records until the proposal is approved and applied

### Requirement: Staged change-set model

The system SHALL model a staged change set as an `AuthoringProposal` containing ordered `ProposedOperation`s, using client-side temp references so an operation can depend on another not-yet-created object in the same proposal.

#### Scenario: Referencing a not-yet-created object

- **WHEN** the LLM proposes a Tower that belongs to a Collection also proposed in the same proposal
- **THEN** the Tower operation SHALL reference the Collection by a temp ref such as `@new:collection-1`
- **AND** the apply engine SHALL resolve that temp ref to the created Collection's real primary key before creating the Tower

#### Scenario: Rejecting unresolvable dependencies

- **WHEN** a proposal's operations form a cyclic or unresolved reference graph
- **THEN** the system SHALL reject the proposal before writing any record
- **AND** SHALL report which references could not be resolved

### Requirement: Creator-scoped authentication and authorization

The system SHALL authenticate each MCP session with a credential bound to a single creator user, and SHALL scope every read, stage, and apply to what that creator is permitted to author, never escalating privileges.

#### Scenario: Credential binds to one creator

- **WHEN** an MCP session authenticates with an `McpCredential`
- **THEN** the server SHALL act as the credential's creator user for all reads and staged writes
- **AND** a revoked or inactive credential SHALL be refused

#### Scenario: Out-of-scope operations are refused

- **WHEN** the LLM stages an operation targeting a Collection, Game, or element the creator may not author
- **THEN** the server SHALL refuse to stage it and SHALL record the refusal in the audit trail
- **AND** the apply engine SHALL re-check authorization as the creator at apply time and SHALL fail any operation the creator is no longer permitted to perform

### Requirement: Human approval is required before apply

The system SHALL require an explicit approval decision by an authorized human before any staged operation is applied, and SHALL NOT allow the MCP/LLM path to approve its own proposals.

#### Scenario: Nothing applies without human approval

- **WHEN** a proposal is submitted for approval
- **THEN** its operations SHALL remain staged and unapplied until an authorized human (the creator or an authorized collaborator) approves them
- **AND** an attempt to apply an unapproved proposal SHALL be refused

#### Scenario: The LLM cannot self-approve

- **WHEN** any MCP tool attempts to approve or apply a proposal
- **THEN** the system SHALL deny it, because approval is a human-only action performed through the staff review surface

### Requirement: Suggest to stage to approve to apply lifecycle

The system SHALL move a proposal through DRAFT, PENDING, APPROVED, and APPLIED states (with REJECTED, PARTIALLY_APPLIED, WITHDRAWN, and FAILED terminal or intermediate states), applying approved operations within the creator's scope in dependency order.

#### Scenario: Applying an approved proposal

- **WHEN** an authorized human approves a proposal and it is applied
- **THEN** the apply engine SHALL create or update the real Collections, Towers, Zones, Challenges, Games, roles, and config values from the approved operations, in dependency order, within the creator's scope
- **AND** each applied operation SHALL record a reference to the resulting object
- **AND** each payload SHALL be validated through the same serializer the staff API uses, so the LLM path cannot produce records the human API could not

#### Scenario: Per-operation curation

- **WHEN** a reviewer approves some operations and rejects others in the same proposal
- **THEN** only the approved operations SHALL be applied
- **AND** the rejected operations SHALL be skipped and marked rejected

#### Scenario: Partial and atomic apply

- **WHEN** an approved operation fails validation or authorization at apply time
- **THEN** the system SHALL mark that operation FAILED with the error and, when the proposal is atomic, SHALL roll back the whole apply, otherwise SHALL apply the successful operations and set the proposal PARTIALLY_APPLIED
- **AND** the failure SHALL be recorded rather than silently dropped

### Requirement: Audit trail of proposals and tool calls

The system SHALL maintain an append-only audit trail recording every tool call, proposal state transition, approval decision, and apply outcome, including the acting creator, the LLM/client identity, and the per-operation rationale.

#### Scenario: Recording what the LLM proposed and why

- **WHEN** the LLM stages an operation, a human decides on a proposal, or the engine applies a proposal
- **THEN** the system SHALL append an immutable `AuthoringAuditEvent` capturing the actor, the LLM model id when known, the event type, a redacted argument/result summary, and the operation rationale
- **AND** audit events SHALL never be updated or deleted

#### Scenario: Reviewing the trail

- **WHEN** a creator or staff user queries the audit trail
- **THEN** the system SHALL return the events for their proposals and sessions, filterable by proposal, session, or creator

### Requirement: Proposal review surface

The system SHALL expose a staff API and staff-app inbox where a human reviews pending proposals, sees each operation's rationale and a diff against current state, and approves, rejects, or withdraws them.

#### Scenario: Reviewing a pending proposal

- **WHEN** a reviewer opens a pending proposal in the staff app
- **THEN** the system SHALL show each proposed operation with its rationale and a diff of the proposed values versus the current state
- **AND** the reviewer SHALL be able to approve or reject per operation or the whole proposal, or withdraw it, and SHALL see the apply results afterward

#### Scenario: Managing MCP credentials

- **WHEN** a creator issues or revokes an MCP credential in the staff app
- **THEN** the system SHALL create or deactivate a creator-scoped credential
- **AND** a revoked credential SHALL immediately stop authenticating new MCP sessions

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
