## 1. Session state model & migration

- [x] 1.1 Add `Session.state` (`CharField` with choices `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, `FINISHED`; default `DRAFT`) and optional `Session.scheduled_start`; migrations + admin display.
- [x] 1.2 Add derived `Session.is_active` property (`state in {OPEN_FOR_PARTICIPANTS, RUNNING, PAUSED}`) plus `is_running()`, `is_paused()`, `is_finished()` helpers.
- [x] 1.3 Data migration: set `state = RUNNING` where `is_active = True`, `state = FINISHED` where `is_active = False`; then set `state = PAUSED` for any Session with an open `PauseWindow`.
- [x] 1.4 Follow-up migration: drop the standalone `is_active` column once no code reads it as a field.

## 2. State machine & transition table

- [x] 2.1 Define the canonical allowed-transition table (from-state → to-state → driving action → effect) as a single source of truth used by both the transition engine and the API.
- [x] 2.2 Implement a `Session.transition(action, *, actor, override=False)` engine that validates the current state against the table, applies the effect atomically, and rejects illegal transitions with HTTP 409.
- [x] 2.3 Expose `Session.allowed_transitions` (the legal next actions for the current state) for serializers and the runner UI.

## 3. Transition actions & endpoints

- [x] 3.1 `open_participation` (`DRAFT → OPEN_FOR_PARTICIPANTS`): open the roster window; enforce the `scheduled_start` timing bound (7 days–1 hour before) with staff `override`.
- [x] 3.2 `close_participation` (`OPEN_FOR_PARTICIPANTS → DRAFT`): re-close the roster window, retaining existing Teams.
- [x] 3.3 `start` (`OPEN_FOR_PARTICIPANTS → RUNNING`): start the Session clock and begin gameplay.
- [x] 3.4 `finish` (`RUNNING → FINISHED` and `PAUSED → FINISHED`): close every open ownership (reusing the deactivation path), close any open `PauseWindow`, preserve history; make `FINISHED` terminal.
- [x] 3.5 Add REST actions `POST /api/staff/sessions/{id}/{open_participation|close_participation|start|resume|finish}/`; expose `state` and `allowed_transitions` on the Session serializer.

## 4. Reconcile day-pausing with the PAUSED state

- [x] 4.1 Route `pause` (`RUNNING → PAUSED`) and `resume` (`PAUSED → RUNNING`) through the transition engine so the state and the `PauseWindow` are opened/closed atomically in one transaction.
- [x] 4.2 Route the bulk `pause_all` endpoint through the same `pause` transition so every affected Session lands in `PAUSED`.
- [x] 4.3 Enforce and document the invariant `state == PAUSED ⟺ Session has a `PauseWindow` with `ended_at IS NULL`; make `is_paused()` return `state == PAUSED`.

## 5. Roster gating in OPEN_FOR_PARTICIPANTS

- [x] 5.1 Permit Team creation and join only while `state == OPEN_FOR_PARTICIPANTS` (and by staff); block Team creation in `DRAFT` and `FINISHED` with a clear error.
- [x] 5.2 Keep player/scoreboard scoping and current-session auto-select driven by the derived `is_active` so `OPEN_FOR_PARTICIPANTS`, `RUNNING`, and `PAUSED` Sessions remain selectable/visible.

## 6. Frontend (staff runner console)

- [x] 6.1 Show the current lifecycle state and render only the legal next actions from `allowed_transitions`.
- [x] 6.2 Lifecycle controls: open/close roster, start, pause/resume, finish; an "open & start" affordance that performs `open_participation` then `start`; out-of-window `open_participation` confirmation for the override.

## 7. Tests

- [x] 7.1 State-machine transition-table test: enumerate all 25 `(from_state, to_state)` pairs and assert exactly the allowed edges succeed and every other pair is rejected with HTTP 409.
- [x] 7.2 Migration test: `is_active=True` Sessions become `RUNNING`, `is_active=False` become `FINISHED`, and open-`PauseWindow` Sessions become `PAUSED`; the same set of Sessions is "active" (derived) before and after.
- [x] 7.3 Pause invariant test: after `pause`/`pause_all` the Session is `PAUSED` with an open `PauseWindow`; after `resume` it is `RUNNING` with the window closed; `state == PAUSED ⟺ open window` holds throughout.
- [x] 7.4 Finish test: finishing from `RUNNING` and from `PAUSED` closes all ownerships, closes any open window, preserves history, and leaves the Session terminal (further transitions 409).
- [x] 7.5 Roster-window test: Teams can be created in `OPEN_FOR_PARTICIPANTS` but not in `DRAFT`/`FINISHED`; `open_participation` honours the 7-day–1-hour `scheduled_start` bound and the staff override.

## Implementation notes

All 24 tasks implemented; 222 backend tests green (208 baseline + 14 new), ruff clean, both Angular apps build.

- **Engine**: `Session.TRANSITIONS` (organize/models.py) is the canonical `(action, from, to)` table used by `Session.transition(action, *, actor, override=False)`, `Session.allowed_transitions`, and the serializer. Illegal transitions raise `organize.models.IllegalTransition`, mapped to HTTP 409 by `AdminSessionViewSet._transition` (`requires_override: true` is included in the 409 body for out-of-window `open_participation`).
- **`can_start()` seam for game-config-team-rules**: `Session._apply_start` does `gate = getattr(self, 'can_start', None); if callable(gate) and not gate(): raise IllegalTransition(...)`, quoting `start_blockers()` if present. This change does NOT implement team-count gating — the sibling branch only needs to add `can_start()` / `start_blockers()` methods to Session and the start transition picks them up.
- **PAUSED invariant**: `PauseWindow.pause_session` / `resume_session` themselves set `session.state` inside their transaction, so legacy model-level callers (tests, shells) can't break `state == PAUSED ⟺ open window`. The staff pause/resume/pause_all endpoints all route through `Session.transition`. `finish` from PAUSED closes the window directly (no restore) then closes ownerships.
- **`is_active`**: now a read-only derived property (`state in Session.ACTIVE_STATES`). All ORM callers were rewritten to `state__in=Session.ACTIVE_STATES` (organize/api.py, game/admin_api.py). The staff `?is_active=` query param still works (translated to state filters); a `?state=` param was added. `start` does not mutate `start_time` (no spec scenario requires it; `scheduled_start` records the planned start).
- **Roster gating scope**: Team creation (staff CRUD → 409 `RosterClosedError`) and invite-join (409) are blocked only in DRAFT/FINISHED. RUNNING/PAUSED joins remain permitted for backward compatibility — gating those belongs to game-config-team-rules per the design's non-goals.
- **Test updates (backward compat)**: test helpers now create default sessions as RUNNING; direct `is_active=...` Session writes became `state=...`; the two "deactivate via PATCH" tests became `finish`-endpoint tests, and a new regression asserts PATCH cannot write `state`/`is_active`. The migration backfill test (`organize.tests.SessionStateMigrationTest`) uses `MigrationExecutor` and migrates 0011→0012, then back to the leaf in tearDown.
- **Migrations**: organize `0011_session_state` (add fields), `0012_backfill_session_state` (data: active→RUNNING, inactive→FINISHED, open-window→PAUSED; reverse noop), `0013_drop_session_is_active`. Numbering conflicts with sibling branches expected; 0012 depends on `game.0021`.
- **Expected merge conflict hotspots**: `organize/models.py` (Session body), `game/admin_api.py` (AdminSessionSerializer/ViewSet), `organize/api.py`, `organize/migrations/001x_*` numbering, `game/tests.py` / `organize/tests.py` (helpers + Session creates), `frontend/projects/shared/src/lib/staff-api.service.ts` (AdminSession shape), `frontend/projects/staff/src/app/admin/session-detail.component.ts`.
- **Frontend**: wireframe Bootstrap controls on the staff session page — lifecycle card with state badge, buttons rendered from `allowed_transitions`, "Open & start" chain on DRAFT, confirm() for finish and for the out-of-window open override. Sessions list shows a read-only state badge (Active switch removed; `is_active`/`state` no longer writable), create form no longer sends `is_active`. Pause/resume moved into the lifecycle card; the old Day pausing card is history-only.
