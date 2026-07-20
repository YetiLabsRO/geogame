## Why

Today a challenge attempt is a single act: a team submits, staff confirms, and `tower.assign_to_team` captures the tower — the last team to complete simply takes it, gated only by the per-tower rejection cooldown. There is no notion of *committing* to a tower, no way to give a team an exclusive window to finish, and no explicit vocabulary for the steps a player walks through. Runners want a choice: either let everyone race for a tower simultaneously (the current feel), or **lock a tower to the team that started it** and give them a finish deadline so a tower cannot be sniped mid-attempt. This change formalizes the challenge lifecycle **identify → initiate → finish** and adds two configurable locking modes, defaulting to today's behavior so nothing changes unless a creator opts in.

## What Changes

- Formalize the challenge lifecycle into three explicit phases: **identify** (a team selects a tower and is served its next challenge), **initiate** (the team commits to attempting that challenge), and **finish** (the team submits the completed challenge for review, and a confirmed finish captures the tower).
- Add a per-Game `tower_lock_mode` config with a nullable per-Session override (resolved by `Session.effective`), with two modes:
  - **`FREE_FOR_ALL`** (default): the tower is only awarded on completion; multiple teams may attempt at once; it ends up owned by the **last** team to finish, passing to whoever finishes next. This plus the existing rejection cooldown is exactly today's behavior.
  - **`LOCK_ON_INITIATE`**: the tower **locks** to the team that initiates a challenge on it, for a configurable finish time-limit. While locked, other teams cannot initiate on that tower. Finishing within the window captures the tower and releases the lock; if the timer expires without a confirmed finish, the lock releases automatically and the tower is free again.
- Add a `game.TowerLock` model (`tower`, `team`, `started_at`, `expires_at`, plus a nullable `released_at` and a `release_reason`) recording each exclusive attempt window.
- Add a per-Game `tower_lock_finish_minutes` default with a nullable per-Session override, controlling the `LOCK_ON_INITIATE` finish deadline.
- Reconcile with the `scoring` ownership-window model: **regardless of mode**, each team that holds a tower accrues for the interval it held it (from winning it until the next team takes it) through the existing `TeamTowerOwnership` window that feeds zone control; a lock that expires without a confirmed finish opens no ownership window and awards no points.
- Locks are scoped **per TeamGroup** so a lock in one group never blocks a co-owning team in another group, consistent with the per-group ownership model.
- New player endpoints for `initiate` (and an idempotent `identify`/next-challenge read), staff visibility of active locks, and a background release of expired locks.

## Capabilities

### New Capabilities
- `tower-locking`: the challenge lifecycle (identify → initiate → finish) and the two locking modes (`FREE_FOR_ALL`, `LOCK_ON_INITIATE`) with a per-Game default and per-Session override, backed by the `TowerLock` model.

### Modified Capabilities
- `challenge-submission`: submission becomes the **finish** step of the formal lifecycle; under `LOCK_ON_INITIATE` a finish is only accepted from the team holding the active lock, and a confirmed finish releases the lock.
- `scoring`: clarifies that a team's tower-hold interval accrues under any lock mode, that the `initial_bonus` is awarded only on a confirmed finish (capture) and never on merely locking, and that an expired lock accrues nothing.

## Impact

- **Models**: new `game.TowerLock` (`tower`, `team`, `started_at`, `expires_at`, `released_at`, `release_reason`) with a partial-unique constraint of one active lock per `(tower, team group)`; new `Game.tower_lock_mode` + `Game.tower_lock_finish_minutes` defaults; new nullable `Session.tower_lock_mode` + `Session.tower_lock_finish_minutes` overrides added to `OVERRIDABLE_CONFIG_FIELDS`.
- **APIs**: new `POST /api/towers/{id}/identify/` (serve next challenge, no commitment) and `POST /api/towers/{id}/initiate/` (acquire a lock under `LOCK_ON_INITIATE`); `POST /api/team_tower_challenges/` (finish) gains lock-holder validation; staff `GET /api/staff/tower_locks/` for active-lock visibility.
- **Frontend**: player app shows tower lock state (locked-by-us / locked-by-others / free), a countdown to the finish deadline, and an explicit "start challenge" (initiate) affordance; staff app surfaces active locks and their timers.
- **Migrations/other**: schema migration for `TowerLock` and the four config fields; a periodic/background task (or lazy check on read) that releases expired locks; defaults chosen so existing Games and Sessions behave exactly as today (`FREE_FOR_ALL`).
