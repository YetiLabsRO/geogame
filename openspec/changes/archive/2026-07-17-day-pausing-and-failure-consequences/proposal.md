## Why

Scouting events span multiple days, so staff need to pause a Session at a day cut-off with no captures or zone-score accrual while players are off the field. Separately, a rejected challenge today costs only a 5-minute cooldown; staff want configurable consequences so that failure carries weight. All behavior is opt-in — defaults preserve current Phase 3 behavior.

## What Changes

- Add a `game.PauseWindow` model (per Session) and pause-behavior knobs on `Game`, overridable per `Session`: `pause_freezes_floating_score`, `pause_restores_ownerships_on_resume`, `pause_rejects_submissions`.
- Add pause/resume endpoints (`POST /api/staff/sessions/{id}/pause/` and `/resume/`) and a `POST /api/staff/games/{id}/pause_all/` bulk action.
- Make floating-score evaluation and challenge submission pause-aware (freeze scoring as of pause start; reject or hold submissions while paused).
- Add combinable, opt-in failure-penalty knobs on `Game` (overridable per `Session`): `fail_point_penalty`, `fail_cooloff_scaling`, `fail_tower_lockout_minutes`, `fail_difficulty_rollback`, and a `fail_counter_reset` enum.
- Track consecutive failures per `(team, tower)` and apply penalties, cooloff scaling, tower lockout, and optional difficulty rollback on rejection.
- Staff UI: pause/resume controls, a "Pause all sessions" action, and observability of lockouts and consecutive-fail counts.

## Capabilities

### New Capabilities
- `day-pausing`: staff-triggered Session pauses with configurable freezing of scoring, ownership restore-on-resume, and submission handling while paused.
- `challenge-failure-consequences`: configurable, opt-in penalties applied when a challenge submission is rejected.

### Modified Capabilities
<!-- None. All new behavior is opt-in and defaults preserve the current spec'd behavior of `scoring`, `challenge-submission`, and `challenges`; the conditional behavior is fully described by the two new capabilities. -->

## Impact

- **Models**: new `game.PauseWindow`; new failure-penalty fields and pause knobs on `organize.Game` and per-`Session` overrides; consecutive-fail tracking per `(team, tower)`.
- **APIs**: new pause/resume/pause_all staff endpoints; `POST /api/team_tower_challenges/` gains paused/lockout handling; next-challenge selection gains difficulty rollback.
- **Scoring**: `Team.floating_score()` becomes pause-aware.
- **Migrations + admin**: new model and config fields; **cross-cutting** across the `game` and `organize` apps.
