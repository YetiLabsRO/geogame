## 1. Session state model & migration

- [ ] 1.1 Add `Session.state` (`CharField` with choices `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, `FINISHED`; default `DRAFT`) and optional `Session.scheduled_start`; migrations + admin display.
- [ ] 1.2 Add derived `Session.is_active` property (`state in {OPEN_FOR_PARTICIPANTS, RUNNING, PAUSED}`) plus `is_running()`, `is_paused()`, `is_finished()` helpers.
- [ ] 1.3 Data migration: set `state = RUNNING` where `is_active = True`, `state = FINISHED` where `is_active = False`; then set `state = PAUSED` for any Session with an open `PauseWindow`.
- [ ] 1.4 Follow-up migration: drop the standalone `is_active` column once no code reads it as a field.

## 2. State machine & transition table

- [ ] 2.1 Define the canonical allowed-transition table (from-state → to-state → driving action → effect) as a single source of truth used by both the transition engine and the API.
- [ ] 2.2 Implement a `Session.transition(action, *, actor, override=False)` engine that validates the current state against the table, applies the effect atomically, and rejects illegal transitions with HTTP 409.
- [ ] 2.3 Expose `Session.allowed_transitions` (the legal next actions for the current state) for serializers and the runner UI.

## 3. Transition actions & endpoints

- [ ] 3.1 `open_participation` (`DRAFT → OPEN_FOR_PARTICIPANTS`): open the roster window; enforce the `scheduled_start` timing bound (7 days–1 hour before) with staff `override`.
- [ ] 3.2 `close_participation` (`OPEN_FOR_PARTICIPANTS → DRAFT`): re-close the roster window, retaining existing Teams.
- [ ] 3.3 `start` (`OPEN_FOR_PARTICIPANTS → RUNNING`): start the Session clock and begin gameplay.
- [ ] 3.4 `finish` (`RUNNING → FINISHED` and `PAUSED → FINISHED`): close every open ownership (reusing the deactivation path), close any open `PauseWindow`, preserve history; make `FINISHED` terminal.
- [ ] 3.5 Add REST actions `POST /api/staff/sessions/{id}/{open_participation|close_participation|start|resume|finish}/`; expose `state` and `allowed_transitions` on the Session serializer.

## 4. Reconcile day-pausing with the PAUSED state

- [ ] 4.1 Route `pause` (`RUNNING → PAUSED`) and `resume` (`PAUSED → RUNNING`) through the transition engine so the state and the `PauseWindow` are opened/closed atomically in one transaction.
- [ ] 4.2 Route the bulk `pause_all` endpoint through the same `pause` transition so every affected Session lands in `PAUSED`.
- [ ] 4.3 Enforce and document the invariant `state == PAUSED ⟺ Session has a `PauseWindow` with `ended_at IS NULL`; make `is_paused()` return `state == PAUSED`.

## 5. Roster gating in OPEN_FOR_PARTICIPANTS

- [ ] 5.1 Permit Team creation and join only while `state == OPEN_FOR_PARTICIPANTS` (and by staff); block Team creation in `DRAFT` and `FINISHED` with a clear error.
- [ ] 5.2 Keep player/scoreboard scoping and current-session auto-select driven by the derived `is_active` so `OPEN_FOR_PARTICIPANTS`, `RUNNING`, and `PAUSED` Sessions remain selectable/visible.

## 6. Frontend (staff runner console)

- [ ] 6.1 Show the current lifecycle state and render only the legal next actions from `allowed_transitions`.
- [ ] 6.2 Lifecycle controls: open/close roster, start, pause/resume, finish; an "open & start" affordance that performs `open_participation` then `start`; out-of-window `open_participation` confirmation for the override.

## 7. Tests

- [ ] 7.1 State-machine transition-table test: enumerate all 25 `(from_state, to_state)` pairs and assert exactly the allowed edges succeed and every other pair is rejected with HTTP 409.
- [ ] 7.2 Migration test: `is_active=True` Sessions become `RUNNING`, `is_active=False` become `FINISHED`, and open-`PauseWindow` Sessions become `PAUSED`; the same set of Sessions is "active" (derived) before and after.
- [ ] 7.3 Pause invariant test: after `pause`/`pause_all` the Session is `PAUSED` with an open `PauseWindow`; after `resume` it is `RUNNING` with the window closed; `state == PAUSED ⟺ open window` holds throughout.
- [ ] 7.4 Finish test: finishing from `RUNNING` and from `PAUSED` closes all ownerships, closes any open window, preserves history, and leaves the Session terminal (further transitions 409).
- [ ] 7.5 Roster-window test: Teams can be created in `OPEN_FOR_PARTICIPANTS` but not in `DRAFT`/`FINISHED`; `open_participation` honours the 7-day–1-hour `scheduled_start` bound and the staff override.
