## Why

The MCP authoring server lets an LLM stage Games and their content (Collections, Towers, Zones, Challenges, roles, config), but a Game is only a template — nothing plays until a Session exists. Today an LLM can author a complete Game and still hand the creator something unrunnable, because `Session` is not a stageable entity and there is no read tool that lists a Game's Sessions.

That last gap already strands a shipped tool: `propose_config(scope='session', target_id=…)` applies overrides to a Session ([authoring/engine.py](../../../authoring/engine.py)), but the LLM has no way to discover a Session's primary key, so the session branch of config staging is unreachable over MCP in practice.

## What Changes

- Add `SESSION` and `TEAM` entity types to the authoring proposal model, so both can be staged, approved, and applied through the existing gate.
- Add read tools `list_sessions` (optionally filtered by Game) and `get_session`, returning the creator's Sessions with their state, window, and which config knobs are overridden versus inherited. This also makes the existing `propose_config(scope='session')` usable.
- Add `propose_session` — stages a Session under an existing or temp-ref'd Game, with `name`, `slug`, `start_time`, `end_time`, and optional `scheduled_start`.
- Add `propose_team` — stages a Team (name, color, description, optional TeamGroup) under an existing or temp-ref'd Session, so a staged Session arrives with its roster shells rather than an empty scoreboard.
- Constrain staged Sessions to the `DRAFT` state. Lifecycle transitions (`open_participation`, `start`, `pause`, `resume`, `finish`) are live operational acts and remain outside the authoring surface entirely — the LLM cannot stage them and the apply engine cannot perform them.
- Exclude player membership from the authoring surface: staged Teams are created empty. Real people join through invites and join codes (the `team-invites` and `player-team-formation` capabilities), never by LLM proposal.
- Extend the config-schema discovery tool to state, per knob, that it is settable at `game` and `session` scope, so the LLM knows an override is available without guessing.

No breaking changes: every addition is a new entity type or a new tool alongside the existing ones.

## Capabilities

### New Capabilities

None. This extends the existing authoring surface rather than introducing a new capability.

### Modified Capabilities

- `mcp-authoring`: the read surface gains Sessions; the suggest-only write tools gain `propose_session` and `propose_team`; new requirements bound staged Sessions to `DRAFT` and keep lifecycle transitions and player membership off the authoring path.

## Impact

- **Code**: `authoring/models.py` (`ENTITY_SESSION`, `ENTITY_TEAM` in `ENTITY_CHOICES`, plus a migration), `authoring/tools.py` (two read tools, two `propose_*` tools), `authoring/mcp_server.py` (tool registration), `authoring/engine.py` (`_MODELS` entries, apply + temp-ref resolution for Session and Team, authorization rules), `authoring/config_schema.py` (scope annotation), `authoring/serializers.py`.
- **Data**: one migration adding choices to `ProposedOperation.entity_type`. No schema change to `organize.Session` or `organize.Team`.
- **APIs**: the staff review surface renders two new entity types in proposal diffs; no endpoint signature changes.
- **Dependencies**: none.
- **Out of scope**: SessionGroups / shared clocks, session cloning from a past run, and any write path to `TeamMembership`.
