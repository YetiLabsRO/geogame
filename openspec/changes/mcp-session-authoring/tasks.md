## 1. Entity types & migration

- [ ] 1.1 Add `ENTITY_SESSION = 'SESSION'` and `ENTITY_TEAM = 'TEAM'` to `authoring/models.py` and extend `ENTITY_CHOICES`.
- [ ] 1.2 Generate and check in the migration altering `ProposedOperation.entity_type` choices (additive; no data backfill).
- [ ] 1.3 Register `Session` and `Team` in `authoring/engine.py` `_MODELS`, and `AdminSessionSerializer` / `AdminTeamSerializer` (from `game/admin_api.py`) in `_CREATE_SERIALIZERS`.

## 2. Authorization

- [ ] 2.1 Extend `authorize_operation` with an `ENTITY_SESSION` branch: resolve the Game from `target.game` for an existing Session, else from the payload's game ref; require `game.can_edit(user)`.
- [ ] 2.2 Extend `authorize_operation` with an `ENTITY_TEAM` branch: resolve Session → Game and require the same, mirroring the existing `ENTITY_CONFIG` Session handling.
- [ ] 2.3 Extend `_resolve_existing_target` in `authoring/tools.py` so real-PK Session and Team targets are loaded for the stage-time scope check.
- [ ] 2.4 Refuse to stage any Team payload carrying member/player/user references, recording the refusal as an audit event.

## 3. Read tools

- [ ] 3.1 Add `AuthoringTools.list_sessions(game_id=None)` returning creator-scoped Sessions with `slug`, `name`, `state`, `start_time`, `end_time`, `scheduled_start`.
- [ ] 3.2 Add `AuthoringTools.get_session(session_id)` returning, per overridable knob, both the Session's own override (or null) and the effective value from `Session.effective`.
- [ ] 3.3 Annotate each knob in `authoring/config_schema.py` with the scopes it accepts (`['game', 'session']` for overridable knobs).
- [ ] 3.4 Register `list_sessions` and `get_session` in `authoring/mcp_server.py`.

## 4. Stage tools

- [ ] 4.1 Add `propose_session(game_ref, name, slug, start_time, end_time, scheduled_start=None, temp_ref='', rationale='', **extra)` staging a Session CREATE operation.
- [ ] 4.2 Strip any lifecycle `state` from a `propose_session` payload so a staged Session can never carry one.
- [ ] 4.3 Add `propose_team(session_ref, name, color, description='', group_ref=None, temp_ref='', rationale='')` staging a Team CREATE operation.
- [ ] 4.4 Reject a session-scoped `propose_config` for a knob absent from `OVERRIDABLE_CONFIG_FIELDS`, reporting the scopes that knob supports.
- [ ] 4.5 Register `propose_session` and `propose_team` in `authoring/mcp_server.py`.

## 5. Apply engine

- [ ] 5.1 Resolve the Game → Session → Team temp-ref chain: register each created Session in the tempmap under its `temp_ref` before Team operations resolve.
- [ ] 5.2 Apply Session and Team CREATE operations through their admin serializers, recording the applied object reference per operation.
- [ ] 5.3 Confirm `state` is never written on apply — `AdminSessionSerializer` already marks it read-only, so assert the behavior rather than adding a second check.
- [ ] 5.4 Ensure a failed Session or Team operation records its error and honors the proposal's atomic flag (full rollback) or marks the proposal PARTIALLY_APPLIED.

## 6. Review surface

- [ ] 6.1 Render Session and Team operations in the staff proposal diff, showing the Session window and state and labeling a staged Team as an empty shell.
- [ ] 6.2 Extend `authoring/serializers.py` so the new entity types serialize in proposal detail responses.

## 7. Tests

- [ ] 7.1 `list_sessions` / `get_session` are creator-scoped and exclude Sessions of Games outside the creator's scope.
- [ ] 7.2 `get_session` reports override-versus-inherited correctly for a knob set on the Session and one left null.
- [ ] 7.3 `propose_session` under an existing Game stages an operation and creates no real Session.
- [ ] 7.4 A Game + Session + Team proposal applies in dependency order with temp refs resolved.
- [ ] 7.5 An applied Session lands in `DRAFT`, including when the payload tried to set another state.
- [ ] 7.6 No published tool performs or stages a lifecycle transition, and no apply path transitions a Session.
- [ ] 7.7 An applied Team has no members, and a Team payload carrying member references is refused at stage time.
- [ ] 7.8 Session and Team operations outside the creator's scope are refused at stage time and re-checked at apply time.
- [ ] 7.9 A session-scoped config override for a non-overridable knob is rejected with the supported scopes reported.
- [ ] 7.10 An invalid time window or a slug colliding within the same Game fails the operation with the error recorded.

## 8. Verification

- [ ] 8.1 Add `authoring` to the test label list in `.github/workflows/ci.yml`, `.claude/guidelines.md`, and `CLAUDE.md` — `authoring/tests.py` shipped with the MCP server but CI runs only `game organize simulator`, so no authoring test has ever run there.
- [ ] 8.2 `coverage run manage.py test game organize simulator authoring --noinput` passes; `coverage report --fail-under=80` holds.
- [ ] 8.3 `ruff check .` is clean.
- [ ] 8.4 `openspec validate mcp-session-authoring --type change --strict` passes.
