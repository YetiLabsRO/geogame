## Why

A Session's lifecycle is today a single `is_active` boolean, which conflates "not yet started", "running", "paused", and "over" into two values. There is no formal state where teams can gather **before** the game starts, no explicit "paused" state (the pause is only inferable from an open `PauseWindow`), and no guardrails on which transitions are legal. This makes runner controls ambiguous and forces every consumer to reconstruct lifecycle from side facts. This change introduces a formal Session state machine — `DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED → FINISHED` — with an explicit set of allowed transitions, each driven by one named staff/runner action, and reconciles it with the existing derived-pause notion.

## What Changes

- Add a `Session.state` field (`DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, `FINISHED`) that replaces `is_active` as the source of truth; `is_active` is retained as a **derived** property so existing callers keep working.
- Define the allowed-transition table and reject every other transition with HTTP 409. Each edge is driven by exactly one runner/staff action: `open_participation`, `close_participation`, `start`, `pause`, `resume`, `finish`.
- Add `OPEN_FOR_PARTICIPANTS` as a distinct pre-start state where Teams and rosters are created and joined **before** `RUNNING`. Add an optional `scheduled_start` to bound when the participation window may open — anywhere from 1 week to 1 hour before the planned start.
- Reconcile the explicit `PAUSED` state with the `day-pausing` capability: a Session is in `PAUSED` **iff** it has an open `PauseWindow`. `pause`/`resume` move the state and open/close the window atomically, keeping the two representations in lockstep.
- `FINISHED` is terminal: it closes all open ownerships (same semantics as the existing Session deactivation / `unassign_all`) and preserves every record for history.
- Data migration: existing active Sessions map to `RUNNING`, inactive Sessions map to `FINISHED`; drop the standalone `is_active` column in favour of the derivation.
- Staff/runner API: transition endpoints on the Session, and a runner control surface exposing the current state, the legal next actions, and the state-machine transition table.

## Capabilities

### New Capabilities
- `session-lifecycle`: a formal Session state machine (`DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED → FINISHED`) with allowed transitions, per-edge driving actions, invariants, and transition endpoints.

### Modified Capabilities
- `game-lifecycle`: "Session deactivation closes its ownerships" is reframed as reaching the `FINISHED` state; ownership-release and history-preservation semantics are unchanged.
- `sessions`: `Session` gains a `state` field as the source of truth; `is_active` becomes a derived property; CRUD deactivation is expressed as lifecycle transitions.
- `day-pausing`: the derived-pause notion ("paused iff an open `PauseWindow`") is reconciled with the explicit `PAUSED` state, which is kept in lockstep with the open window.

## Impact

- **Models**: add `Session.state` (CharField with choices) and optional `Session.scheduled_start`; add a `Session.is_active` derived property and `Session.is_paused()`/`is_running()` helpers; keep `PauseWindow` as-is (`day-pausing`).
- **APIs**: new transition actions `POST /api/staff/sessions/{id}/open_participation|close_participation|start|resume|finish/` (pause/resume already exist under `day-pausing`); Session serializers expose `state` and `allowed_transitions`.
- **Migrations**: data migration mapping `is_active=True → RUNNING`, `is_active=False → FINISHED`, then removing the standalone `is_active` column; backfill leaves runtime behaviour unchanged.
- **Frontend**: staff runner console gains lifecycle controls (open roster, start, pause/resume, finish) that show the current state and only the legal next actions.
