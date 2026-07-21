## 1. Config knobs (per-Game default + per-Session override)

- [x] 1.1 Add `Game.tower_lock_mode` (`CharField` choices `FREE_FOR_ALL` (default) / `LOCK_ON_INITIATE`) and `Game.tower_lock_finish_minutes` (`PositiveSmallIntegerField`, default 15).
- [x] 1.2 Add nullable `Session.tower_lock_mode` and `Session.tower_lock_finish_minutes` overrides; add both names to `OVERRIDABLE_CONFIG_FIELDS`; verify `Session.effective(...)` resolves override-or-default.
- [x] 1.3 Migration for the four fields; confirm existing rows read back as `FREE_FOR_ALL` (behavior-preserving default).
- [x] 1.4 Expose the knobs on the Game/creator config surface and the Session override surface (admin + staff API serializers).

## 2. TowerLock model

- [x] 2.1 Add `game.TowerLock` (`tower` FK, `team` FK, `started_at`, `expires_at`, nullable `released_at`, `release_reason` choices `FINISHED`/`EXPIRED`/`CANCELLED`) with `__str__` and admin registration.
- [x] 2.2 Add a partial-unique constraint: at most one lock with `released_at IS NULL` per `(tower, team.group)` (store/derive group for the constraint).
- [x] 2.3 Add helpers: `Tower.active_lock(group)` (honors lazy expiry), `TowerLock.is_active(now)`, and a `release(reason)` that only sets `released_at` when currently null (idempotent).
- [x] 2.4 Migration for `TowerLock`.

## 3. Lifecycle: identify → initiate → finish

- [x] 3.1 `POST /api/towers/{id}/identify/`: return the caller team's next challenge via `get_next_challenge`, with no side effects; idempotent/repeatable.
- [x] 3.2 `POST /api/towers/{id}/initiate/`: under `LOCK_ON_INITIATE`, create a `TowerLock(started_at=now, expires_at=now + effective(tower_lock_finish_minutes))`; refuse (409) if another team in the caller's group holds an active lock; under `FREE_FOR_ALL`, succeed as a side-effect-free acknowledgement.
- [x] 3.3 Finish path (`POST /api/team_tower_challenges/`): under `LOCK_ON_INITIATE`, reject a submission from a team that is not the active lock holder for its group while a lock is active; under `FREE_FOR_ALL`, unchanged.
- [x] 3.4 On confirmed finish under `LOCK_ON_INITIATE`, after `assign_to_team` runs, release the team's active lock with `release_reason=FINISHED`.
- [x] 3.5 Optional voluntary release: allow the lock-holding team (or staff) to `CANCELLED`-release its own lock early.

## 4. Expiry handling

- [x] 4.1 Make every lock read treat `expires_at <= now, released_at IS NULL` as free (lazy expiry) so initiation is never blocked by an already-expired lock.
- [x] 4.2 Add an expired-lock sweep (management command / periodic task) that sets `released_at`/`release_reason=EXPIRED`; register it and make it idempotent.

## 5. Scoring reconciliation

- [x] 5.1 Verify capture still flows through `assign_to_team` in both modes (closes prior same-group `TeamTowerOwnership`, opens the new window, awards `initial_bonus`).
- [x] 5.2 Verify an expired/`CANCELLED` lock with no confirmed finish opens no `TeamTowerOwnership` window and awards no points.

## 6. Staff & player surfaces

- [x] 6.1 Staff `GET /api/staff/tower_locks/`: list active locks (tower, team, group, started_at, expires_at, remaining seconds).
- [x] 6.2 Player app: show per-tower lock state (locked-by-us / locked-by-others / free), a finish-deadline countdown, and an explicit "start challenge" (initiate) affordance; fall back to free-for-all UI when the mode is `FREE_FOR_ALL`.
- [x] 6.3 Staff app: surface active locks and their timers on the review/monitoring view.

## 7. Tests

- [x] 7.1 `Session.effective` returns the Game default when the Session override is null and the override when set, for both new fields.
- [x] 7.2 `LOCK_ON_INITIATE`: initiating creates an active lock; a second team in the same group is blocked from initiating and from finishing while the lock is active.
- [x] 7.3 `LOCK_ON_INITIATE`: a finish within the window captures the tower (via `assign_to_team`) and releases the lock with `FINISHED`.
- [x] 7.4 `LOCK_ON_INITIATE`: lock expiry frees the tower (lazy-on-read and via the sweep); an expired lock opens no ownership window and awards no `initial_bonus`.
- [x] 7.5 Per-group isolation: a lock held by a team in one TeamGroup does not block a team in another group from initiating/finishing on the same tower.
- [x] 7.6 `FREE_FOR_ALL` (default): multiple teams may attempt at once; the last confirmed finish owns the tower; the rejection cooldown still applies — asserting no behavior change vs today.
- [x] 7.7 Ownership-window reconciliation: in both modes, a team accrues for its hold interval (win until the next team takes it) through the `TeamTowerOwnership` window that feeds zone control.
- [x] 7.8 Concurrency: two simultaneous initiates on the same `(tower, group)` — exactly one succeeds (partial-unique constraint); releases are idempotent.
- [x] 7.9 Coverage ≥80% branch on new code; ruff-clean; single-quoted Python.

## Implementation notes

- **Test result**: `manage.py test game organize --noinput` — 454 tests, all green
  (412 baseline + 42 new in `game/tests.py`). Ruff clean. `makemigrations --check` clean.
- **Migrations**: `game/migrations/0026_towerlock.py` (TowerLock + partial-unique
  `unique_active_tower_lock_per_group`), `organize/migrations/0018_tower_lock_config.py`
  (Game defaults + Session overrides). Numbering conflicts with parallel branches expected;
  both depend on the current `0025`/`0017` merge heads.
- **`TowerLock.group` is denormalized** from `team.group` at acquire time so the
  partial-unique constraint (`released_at IS NULL` per `(tower, group)`) can target the
  group column directly. `TowerLock.acquire()` is the single acquisition path: it lazily
  EXPIRE-releases lapsed locks on that (tower, group), is idempotent for the current
  holder, and maps a concurrent-insert `IntegrityError` to "lost the race" (409 upstream).
- **Submission serializer check order** (`TeamTowerChallengeSerializer.validate`): the
  foreign-lock check (`TowerLockHeldError`, 409 `tower_lock_held`) is appended AFTER the
  existing membership → tower/RFID → GPS → role gate → pause → failure-lockout checks, so
  every pre-existing rejection keeps its current precedence; under `FREE_FOR_ALL` it is a
  no-op.
- **Stale-finish defense is enforced at confirm time too**: `StaffSubmissionReview` 409s a
  `confirm` for a submission whose team is not the active lock holder (a pending submission
  can outlive the lock that admitted it).
- **Release points**: confirmed finish → `Tower.assign_to_team` closes the capturer's
  still-active lock with `FINISHED` (expired locks are deliberately left for the sweep to
  stamp `EXPIRED`); voluntary release → `POST /api/towers/{id}/release_lock/` (holder only,
  `CANCELLED`); staff force-release → `POST /api/staff/tower_locks/{id}/cancel/`.
- **Sweep**: `manage.py release_expired_locks` (idempotent; pins `released_at` to
  `expires_at`). No scheduler infra exists in the repo, so it must be cron'd at deploy;
  lazy-on-read makes it a tidy-up, not a correctness dependency.
- **New endpoints**: player `POST /api/towers/{id}/identify|initiate|release_lock/`;
  `GET /api/towers/{id}/state/` now includes `tower_lock_mode` + `lock` payload; staff
  `GET /api/staff/tower_locks/` (+ `POST {id}/cancel/`), session-scoped via
  `team__session`, list filtered to active locks only.
- **Frontend (wireframe)**: player `tower-detail.component.ts` shows
  locked-by-us / locked-by-others banners with a ticking finish-deadline countdown, gates
  photo+submit behind an explicit "Start challenge (lock this tower)" initiate button in
  `LOCK_ON_INITIATE`, and offers "Give up lock"; `FREE_FOR_ALL` UI is unchanged. Staff:
  new `review/active-locks.component.ts` (list + countdown + cancel) embedded at the
  bottom of the review queue (task 6.3's review/monitoring view). Shared lib gained
  `TowerLockInfo`/`TowerLockMode`/`StaffTowerLock` types and
  `initiateTower`/`releaseTowerLock`/`listTowerLocks`/`cancelTowerLock`. Both apps build
  (`ng build player|staff --configuration development`).
- **Expected merge-conflict hotspots**: `game/models.py`, `game/api.py`,
  `game/serializers.py`, `game/admin_api.py`, `game/admin.py`, `geogame/urls.py`,
  `organize/models.py` (`OVERRIDABLE_CONFIG_FIELDS` + knob blocks), `game/tests.py`
  (appended test classes), `frontend/projects/shared/src/lib/game-api.service.ts` /
  `staff-api.service.ts`, `pending-queue.component.ts`, `tower-detail.component.ts`, and
  migration numbering (`game/0026`, `organize/0018`).
