## Context

The `mcp-authoring` capability ships a suggest → stage → approve → apply pipeline: MCP tools append `ProposedOperation` rows to an `AuthoringProposal`, a human approves, and `authoring/engine.py` applies each operation through the same serializer the staff API uses. Entity coverage stops at `COLLECTION`, `TOWER`, `ZONE`, `CHALLENGE`, `GAME`, `GAME_ROLE`, `CONFIG`.

`organize.Session` is the unit that actually runs: it owns the roster (`Team.session`), the clock, and per-session config overrides resolved by `Session.effective(field)` against `OVERRIDABLE_CONFIG_FIELDS`. An LLM can therefore author a complete Game today and still produce nothing playable.

Two constraints shape this design. First, `Session` carries a lifecycle (`DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING → PAUSED → FINISHED`) whose transitions are live operational acts with real consequences for players mid-game. Second, `Team` reaches real people through `TeamMembership` → `UserProfile`.

## Goals / Non-Goals

**Goals:**

- An LLM can stage a runnable Session under a Game — existing or proposed in the same proposal — and the Teams that will play it.
- The LLM can read a Game's Sessions, which also makes the already-shipped `propose_config(scope='session')` reachable.
- Session and Team staging inherit the existing gate unchanged: same proposal model, same human approval, same audit trail, same temp-ref resolution.

**Non-Goals:**

- Driving lifecycle transitions. `open_participation`, `start`, `pause`, `resume`, `finish` stay off the authoring surface in both directions — not stageable, not applicable.
- Writing player membership. No `TeamMembership` write path, no roster filled with real users.
- SessionGroups / shared clocks, and cloning a Session from a past run.

## Decisions

### Session and Team as ordinary entity types, not a bespoke path

Add `ENTITY_SESSION` and `ENTITY_TEAM` to `ENTITY_CHOICES` and register them in `_MODELS`, `_CREATE_SERIALIZERS`, and `authorize_operation` like every other entity.

*Alternative considered:* a dedicated "provision a session" compound tool that creates Session plus Teams in one operation. Rejected — it would produce one opaque `ProposedOperation` that the staff reviewer cannot curate per item, breaking the shipped per-operation approve/reject requirement. Ordinary entities keep review granularity.

### Reuse `AdminSessionSerializer` and `AdminTeamSerializer` from `game/admin_api.py`

The existing spec already requires each payload to validate through the same serializer the staff API uses, so the LLM path cannot produce records the human API could not.

This choice also delivers the DRAFT guardrail for free: `AdminSessionSerializer` already lists `state` in `read_only_fields`, and `Session.state` defaults to `DRAFT`. A staged Session therefore lands in `DRAFT` because the serializer refuses to write `state` at all — not because a second hand-written check says so. One source of truth, no drift.

*Alternative considered:* an explicit `if payload.get('state') != DRAFT: raise` in the apply engine. Rejected as a redundant check that could disagree with the serializer later.

### Authorization delegates to `Game.can_edit`

A Session's scope is its Game's. `authorize_operation` gains:

- `ENTITY_SESSION`: resolve the Game (from `target.game` for an existing Session, else from the payload's `game` ref) and require `game.can_edit(user)`.
- `ENTITY_TEAM`: resolve the Session, then its Game, and require the same.

This mirrors `ENTITY_CONFIG`, which already does `target.game if isinstance(target, Session) else target`, so Session-rooted authorization is a pattern the engine has rather than a new one.

### Temp refs chain one level deeper

Today's deepest chain is Collection → Tower. Sessions add Game → Session → Team. `_resolve_target` and the payload ref resolution already walk a `tempmap`, so the chain extends by registering each created Session in the map under its `temp_ref` before Team operations resolve. Operations are applied in dependency order, and the shipped cycle detection covers the new edges without change.

### Read tools report override provenance, not just values

`list_sessions` / `get_session` return each overridable knob as the pair (session override or null, effective value), computed via `Session.effective`. A bare effective value would let the LLM propose an override identical to the inherited default — noise the human then has to review. Showing "inherited" versus "overridden" lets it propose only real deltas.

### Config-schema annotation instead of a second tool

`describe_config_schema` already emits `overridable_per_session: True` per knob. Extend that entry with the scope names it accepts (`['game', 'session']`) rather than adding a session-specific schema tool. The catalog stays derived from live field definitions, so newly added knobs keep appearing without hand maintenance.

## Risks / Trade-offs

- **An LLM stages a Session whose window overlaps a live run on the same Game** → `AdminSessionSerializer.validate` already resolves and checks session fields; apply-time validation runs it, so the conflict surfaces as a failed operation with an error rather than a bad record. The reviewer also sees the window in the diff before approving.

- **Teams staged empty look like a half-finished job to a creator who expected rosters** → the read tools and the proposal diff label a staged Team as a shell to be joined via invite or join code. This is the intended boundary, not an omission: an LLM must not assert who plays on which team.

- **Approval latency makes a staged Session stale** — `start_time` may be in the past by the time a human approves → apply-time serializer validation catches an invalid window and fails that operation rather than creating an unrunnable Session. The proposal stays reviewable and the operation is re-stageable with a new window.

- **Deeper temp-ref chains raise the cost of a cycle** → cycles are already rejected before any write, and the failure names the unresolvable refs. The new edges add no new failure mode, only more places the existing one can fire.

## Migration Plan

One migration altering `ProposedOperation.entity_type` choices — additive, no data backfill, no change to `organize.Session` or `organize.Team`. Existing proposals are unaffected because no stored row uses the new values.

Rollback is the reverse migration plus removing the four tools; staged operations of the new types would become unknown entity types, which `authorize_operation` already rejects with `Unknown entity type`, so a rollback fails closed rather than applying something unrecognized.

## Open Questions

- Should `propose_team` accept a `TeamGroup` by name as well as by ref? Name is friendlier for an LLM but ambiguous across Games; starting with ref only, pending creator feedback.
- Should a staged Session be allowed to carry its config overrides inline in `propose_session`, or must they come as a separate `propose_config` operation against the resulting temp ref? Separate operations keep per-operation curation sharper; inline is fewer round trips. Starting separate.
