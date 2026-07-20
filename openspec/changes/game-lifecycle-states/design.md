## Context

Today `organize.Session` carries a single `is_active` boolean. "Active" means "visible in player and scoreboard views"; "inactive" means "archived to history, ownerships closed". Pausing is layered on separately by `day-pausing`: a Session is considered paused **iff** it has a `PauseWindow` with `ended_at IS NULL`. So the true lifecycle is spread across one boolean plus the existence of an open window, with nothing to represent "teams are gathering but the game has not started". The product needs teams to be creatable **before** the game starts, an explicit paused state, and legal-transition guardrails so runner controls are unambiguous. This change promotes the lifecycle to a first-class state machine while preserving every current behaviour and staying compatible with `day-pausing`.

## Goals / Non-Goals

**Goals:**
- One authoritative `Session.state` with five values: `DRAFT`, `OPEN_FOR_PARTICIPANTS`, `RUNNING`, `PAUSED`, `FINISHED`.
- A single, enumerated allowed-transition table; every other transition rejected with HTTP 409.
- Each transition driven by exactly one named runner/staff action.
- A distinct pre-start `OPEN_FOR_PARTICIPANTS` window where Teams and rosters form, openable 1 week to 1 hour before the planned start.
- The explicit `PAUSED` state kept in lockstep with `day-pausing`'s open-`PauseWindow` predicate (neither can be true without the other).
- `FINISHED` closes ownerships and preserves history, identical to today's Session deactivation.
- Zero behavioural change for existing Sessions: active → `RUNNING`, inactive → `FINISHED`; `is_active` still readable.

**Non-Goals:**
- Automatic/scheduled transitions (starting, pausing, or finishing on a timer) — pauses stay staff-triggered (`day-pausing`), and start/finish stay explicit runner actions. A later change may add scheduling.
- Team-count start-gating thresholds (min/max teams before `start`) — owned by the separate `game-config-team-rules` change; this change only provides the state where rosters gather.
- Any change to pause side effects (floating-score freeze, submission handling, ownership restore) — those requirements in `day-pausing` are unchanged.
- Per-`TeamGroup` or per-Team lifecycle — the state machine is per-Session.

## Decisions

- **`state` is a `CharField` with `choices`, and is the source of truth.** `is_active` becomes a derived read-only property (`state in {OPEN_FOR_PARTICIPANTS, RUNNING, PAUSED}`) so the ~existing callers of `session.is_active` (player/scoreboard scoping, current-session auto-select) keep working unchanged. Alternative considered: an integer/enum ordering column — rejected because the transitions are not a linear order (`RUNNING ⇄ PAUSED` is bidirectional) and named choices read better in admin/serializers.
- **The allowed transitions are exactly these edges; anything else is a 409.** Modelling every edge explicitly (rather than "any forward move") is what makes runner controls safe:

  | From | To | Action | Effect |
  |---|---|---|---|
  | `DRAFT` | `OPEN_FOR_PARTICIPANTS` | `open_participation` | opens the roster window; Teams may be created/joined |
  | `OPEN_FOR_PARTICIPANTS` | `DRAFT` | `close_participation` | re-closes the roster window; existing Teams are retained |
  | `OPEN_FOR_PARTICIPANTS` | `RUNNING` | `start` | starts the Session clock; gameplay begins |
  | `RUNNING` | `PAUSED` | `pause` | opens a `PauseWindow` (see `day-pausing`) |
  | `PAUSED` | `RUNNING` | `resume` | closes the newest open `PauseWindow` |
  | `RUNNING` | `FINISHED` | `finish` | closes all open ownerships; preserves history |
  | `PAUSED` | `FINISHED` | `finish` | closes the open `PauseWindow`, then closes ownerships |

  `FINISHED` is terminal (no outbound edges). `DRAFT ⇄ OPEN_FOR_PARTICIPANTS` and `RUNNING ⇄ PAUSED` are the only reversible pairs. Alternative considered: allow a direct `DRAFT → RUNNING` fast-path — rejected so that "teams are creatable before the game starts" is guaranteed by always passing through `OPEN_FOR_PARTICIPANTS`; a runner who wants to start immediately performs `open_participation` then `start`.
- **`PAUSED` is defined to be exactly "has an open `PauseWindow`".** `pause` performs `RUNNING → PAUSED` **and** opens a `PauseWindow` in one atomic action; `resume` performs `PAUSED → RUNNING` **and** closes the newest open window atomically. The invariant `state == PAUSED ⟺ ∃ PauseWindow with ended_at IS NULL` is enforced, so `day-pausing`'s existing predicate and the explicit state can never disagree. `Session.is_paused()` returns `state == PAUSED`. All pause side effects (`pause_freezes_floating_score`, `pause_restores_ownerships_on_resume`, `pause_rejects_submissions`) remain owned by `day-pausing` and are unchanged.
- **`OPEN_FOR_PARTICIPANTS` is when rosters form.** Team creation/join is permitted in this state (and blocked in `DRAFT`/`FINISHED`). An optional `Session.scheduled_start` records the planned `RUNNING` time; when set, `open_participation` is permitted only within `[scheduled_start − 7 days, scheduled_start − 1 hour]`, with an explicit staff override for out-of-window opens. When `scheduled_start` is unset, the window may open at any time.
- **`FINISHED` reuses the current deactivation path.** Reaching `FINISHED` closes all open `TeamTowerOwnership`/`TeamZoneOwnership` (same semantics as `unassign_all` / today's `is_active=False`) and preserves every record for `session-history`. Finishing from `PAUSED` first closes the open `PauseWindow` (without reopening ownerships) and then closes ownerships.
- **Migration maps the boolean to the state, then drops it.** `is_active=True → RUNNING`; `is_active=False → FINISHED`; the standalone column is removed and `is_active` is reintroduced as a property. This preserves the exact set of Sessions shown in each view.

## Risks / Trade-offs

- [Consumers read `session.is_active` directly and would break if the column vanished] → Keep `is_active` as a derived property returning `state in {OPEN_FOR_PARTICIPANTS, RUNNING, PAUSED}`; add a regression test that the same Sessions are "active" before and after migration.
- [The explicit `PAUSED` state and `day-pausing`'s open-window predicate could drift] → Make `pause`/`resume` the only writers of both, perform them atomically in one transaction, and add an invariant test asserting `state == PAUSED ⟺ open PauseWindow`.
- [Existing `pause_all` bulk endpoint opens windows without setting the new state] → Route the bulk path through the same `pause` transition so every affected Session lands in `PAUSED`; test that bulk-paused Sessions report `state == PAUSED`.
- [A runner expects to start straight from `DRAFT`] → UI offers a single "open & start" affordance that performs `open_participation` then `start`; the state machine still records the intermediate state so rosters are always openable.
- [Out-of-window `open_participation` (too early/too late) is over-restrictive for ad-hoc runs] → The 1-week/1-hour bound only applies when `scheduled_start` is set, and staff may override with explicit confirmation.

## Migration Plan

1. Add `Session.state` (choices, default `DRAFT` for new rows) and optional `Session.scheduled_start`; keep the existing `is_active` column temporarily.
2. Data migration: set `state = RUNNING` where `is_active = True`, `state = FINISHED` where `is_active = False`.
3. Reconcile pause: for any Session with an open `PauseWindow`, set `state = PAUSED` (so the invariant holds immediately post-migration).
4. Replace direct writes/reads of `is_active` with the state machine and the derived `is_active` property; route pause/resume/`pause_all` through the transitions.
5. Follow-up migration: drop the standalone `is_active` column once no code reads it as a field.
