## 1. Config knobs (per-Game default + per-Session override)

- [ ] 1.1 Add `Game.tower_lock_mode` (`CharField` choices `FREE_FOR_ALL` (default) / `LOCK_ON_INITIATE`) and `Game.tower_lock_finish_minutes` (`PositiveSmallIntegerField`, default 15).
- [ ] 1.2 Add nullable `Session.tower_lock_mode` and `Session.tower_lock_finish_minutes` overrides; add both names to `OVERRIDABLE_CONFIG_FIELDS`; verify `Session.effective(...)` resolves override-or-default.
- [ ] 1.3 Migration for the four fields; confirm existing rows read back as `FREE_FOR_ALL` (behavior-preserving default).
- [ ] 1.4 Expose the knobs on the Game/creator config surface and the Session override surface (admin + staff API serializers).

## 2. TowerLock model

- [ ] 2.1 Add `game.TowerLock` (`tower` FK, `team` FK, `started_at`, `expires_at`, nullable `released_at`, `release_reason` choices `FINISHED`/`EXPIRED`/`CANCELLED`) with `__str__` and admin registration.
- [ ] 2.2 Add a partial-unique constraint: at most one lock with `released_at IS NULL` per `(tower, team.group)` (store/derive group for the constraint).
- [ ] 2.3 Add helpers: `Tower.active_lock(group)` (honors lazy expiry), `TowerLock.is_active(now)`, and a `release(reason)` that only sets `released_at` when currently null (idempotent).
- [ ] 2.4 Migration for `TowerLock`.

## 3. Lifecycle: identify → initiate → finish

- [ ] 3.1 `POST /api/towers/{id}/identify/`: return the caller team's next challenge via `get_next_challenge`, with no side effects; idempotent/repeatable.
- [ ] 3.2 `POST /api/towers/{id}/initiate/`: under `LOCK_ON_INITIATE`, create a `TowerLock(started_at=now, expires_at=now + effective(tower_lock_finish_minutes))`; refuse (409) if another team in the caller's group holds an active lock; under `FREE_FOR_ALL`, succeed as a side-effect-free acknowledgement.
- [ ] 3.3 Finish path (`POST /api/team_tower_challenges/`): under `LOCK_ON_INITIATE`, reject a submission from a team that is not the active lock holder for its group while a lock is active; under `FREE_FOR_ALL`, unchanged.
- [ ] 3.4 On confirmed finish under `LOCK_ON_INITIATE`, after `assign_to_team` runs, release the team's active lock with `release_reason=FINISHED`.
- [ ] 3.5 Optional voluntary release: allow the lock-holding team (or staff) to `CANCELLED`-release its own lock early.

## 4. Expiry handling

- [ ] 4.1 Make every lock read treat `expires_at <= now, released_at IS NULL` as free (lazy expiry) so initiation is never blocked by an already-expired lock.
- [ ] 4.2 Add an expired-lock sweep (management command / periodic task) that sets `released_at`/`release_reason=EXPIRED`; register it and make it idempotent.

## 5. Scoring reconciliation

- [ ] 5.1 Verify capture still flows through `assign_to_team` in both modes (closes prior same-group `TeamTowerOwnership`, opens the new window, awards `initial_bonus`).
- [ ] 5.2 Verify an expired/`CANCELLED` lock with no confirmed finish opens no `TeamTowerOwnership` window and awards no points.

## 6. Staff & player surfaces

- [ ] 6.1 Staff `GET /api/staff/tower_locks/`: list active locks (tower, team, group, started_at, expires_at, remaining seconds).
- [ ] 6.2 Player app: show per-tower lock state (locked-by-us / locked-by-others / free), a finish-deadline countdown, and an explicit "start challenge" (initiate) affordance; fall back to free-for-all UI when the mode is `FREE_FOR_ALL`.
- [ ] 6.3 Staff app: surface active locks and their timers on the review/monitoring view.

## 7. Tests

- [ ] 7.1 `Session.effective` returns the Game default when the Session override is null and the override when set, for both new fields.
- [ ] 7.2 `LOCK_ON_INITIATE`: initiating creates an active lock; a second team in the same group is blocked from initiating and from finishing while the lock is active.
- [ ] 7.3 `LOCK_ON_INITIATE`: a finish within the window captures the tower (via `assign_to_team`) and releases the lock with `FINISHED`.
- [ ] 7.4 `LOCK_ON_INITIATE`: lock expiry frees the tower (lazy-on-read and via the sweep); an expired lock opens no ownership window and awards no `initial_bonus`.
- [ ] 7.5 Per-group isolation: a lock held by a team in one TeamGroup does not block a team in another group from initiating/finishing on the same tower.
- [ ] 7.6 `FREE_FOR_ALL` (default): multiple teams may attempt at once; the last confirmed finish owns the tower; the rejection cooldown still applies — asserting no behavior change vs today.
- [ ] 7.7 Ownership-window reconciliation: in both modes, a team accrues for its hold interval (win until the next team takes it) through the `TeamTowerOwnership` window that feeds zone control.
- [ ] 7.8 Concurrency: two simultaneous initiates on the same `(tower, group)` — exactly one succeeds (partial-unique constraint); releases are idempotent.
- [ ] 7.9 Coverage ≥80% branch on new code; ruff-clean; single-quoted Python.
