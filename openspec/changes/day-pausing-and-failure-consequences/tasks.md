## 1. Day Pausing — model & config

- [x] 1.1 Add `game.PauseWindow` model (`session` FK, `started_at`, `ended_at` nullable, snapshots of closed tower + zone ownerships); migrations + admin.
- [x] 1.2 Add pause-behavior knobs to `Game` (`pause_freezes_floating_score`, `pause_restores_ownerships_on_resume`, `pause_rejects_submissions`, all default `True`) with nullable per-`Session` overrides and an effective-value helper.

## 2. Day Pausing — endpoints

- [x] 2.1 Implement `POST /api/staff/sessions/{id}/pause/`: open a `PauseWindow`; close active `TeamTowerOwnership` / `TeamZoneOwnership` at `timestamp_end = window.started_at` and record them when restore is enabled.
- [x] 2.2 Implement `POST /api/staff/sessions/{id}/resume/`: close the newest open window; when restore is enabled, reopen matching ownership rows with `timestamp_start = resume_time`, reconciling against captures made while unpaused.
- [x] 2.3 Implement `POST /api/staff/games/{id}/pause_all/`: open a `PauseWindow` on every active Session of the game in one call.

## 3. Day Pausing — scoring & submissions

- [x] 3.1 Make `Team.floating_score()` evaluate as of the open window's `started_at` when the effective `pause_freezes_floating_score` is `True`.
- [x] 3.2 Update the submission serializer: while paused, return HTTP 409 when the effective `pause_rejects_submissions` is `True`; otherwise store `PENDING` without triggering capture until resume.

## 4. Day Pausing — staff UI & tests

- [ ] 4.1 Staff UI: pause/resume buttons on the Session detail page, a "Pause all sessions" button on the Game page, and current pause state + pause history.
- [x] 4.2 Tests: pause/resume round-trip restores ownerships; frozen floating score returns identical values during the window; submission returns 409 when configured to reject; per-session override beats game default.

## 5. Failure Consequences — config & tracking

- [x] 5.1 Add failure-penalty fields to `Game` with per-`Session` overrides: `fail_point_penalty`, `fail_cooloff_scaling`, `fail_tower_lockout_minutes`, `fail_difficulty_rollback`, `fail_counter_reset` (enum `TOWER_SUCCESS_ONLY` / `ANY_SUCCESS_ELSEWHERE` / `ANY_ATTEMPT_ELSEWHERE`, default `TOWER_SUCCESS_ONLY`); migrations + admin.
- [x] 5.2 Track consecutive failures per `(team, tower)` (dedicated model with `consecutive_fails`, `last_failed_at`, `locked_until`).

## 6. Failure Consequences — apply on rejection

- [x] 6.1 On REJECT, atomically subtract `fail_point_penalty` from `Team.score` (clamped to ≥ 0) and set `locked_until = now + fail_tower_lockout_minutes`.
- [x] 6.2 Scale the team/tower cooloff by `fail_cooloff_scaling ^ consecutive_fails`; wire into `Tower.team_in_cooloff` and the submission serializer's lockout check.
- [x] 6.3 Extend next-challenge selection so that when `fail_difficulty_rollback` is `True` and the team has outstanding consecutive fails on the tower, the next challenge is drawn from the next-lower difficulty bucket.
- [x] 6.4 Implement `fail_counter_reset` semantics for each enum value (tower-success only / any success elsewhere / any attempt elsewhere).

## 7. Failure Consequences — staff UI & tests

- [ ] 7.1 Staff UI: per-Game form for the five failure knobs plus optional per-Session override; scoreboard/timeline shows current lockouts and consecutive-fail counts.
- [x] 7.2 Tests: REJECT subtracts points clamped to ≥ 0; cooloff scales as `base × scaling^n`; lockout blocks submissions for exactly `fail_tower_lockout_minutes`; difficulty rollback picks from the lower bucket; each reset-enum value behaves as specified; no cross-team side effects.
