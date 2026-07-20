## Context

Today the challenge flow is implicit: `Tower.get_next_challenge(team)` serves a challenge, the player submits a `TeamTowerChallenge` (outcome `PENDING`) via `POST /api/team_tower_challenges/`, staff confirms, and `Tower.assign_to_team(team)` captures the tower — closing the prior same-group team's `TeamTowerOwnership` window and opening a new one. The only contention control is `Tower.team_in_cooloff(team)`, a per-tower rejection cooldown. Whoever completes last owns the tower; nothing reserves it while a team is mid-attempt.

The product wants a runner-selectable contention model. Two modes cover the design space: keep the free-for-all race (today), or lock a tower to the first team that commits and give them a bounded window to finish. This change also names the three lifecycle phases so the rest of the expansion (visibility, presence, roles-as-mechanics) can hook into consistent verbs. Ownership records and their scoring windows are per **TeamGroup** (a tower can be simultaneously owned by one team in each group), so locking must respect the same axis.

## Goals / Non-Goals

**Goals:**
- Name the lifecycle phases **identify → initiate → finish** with clear, testable transitions.
- Add two locking modes selectable per Game with a per-Session override via the existing `Session.effective` pattern.
- `LOCK_ON_INITIATE`: initiating locks the tower to that team (per group) for a finish deadline; other teams in that group cannot initiate; expiry frees it; a confirmed finish captures and releases.
- `FREE_FOR_ALL` (default) preserves today's behavior exactly: simultaneous attempts, last confirmed finish owns, existing rejection cooldown intact.
- Preserve the `scoring` ownership-window model: each holder accrues for its hold interval in either mode; an expired lock accrues nothing.
- Zero behavior change for existing Games/Sessions until a creator/runner opts in.

**Non-Goals:**
- Changing how points are computed (zone functions, floating vs locked score) — only *who may capture and when* changes; accrual mechanics are unchanged.
- Reworking the rejection cooldown (`cooloff_minutes`) — it coexists with both modes; `FREE_FOR_ALL` + cooldown == today.
- Queuing/reservations beyond a single active lock per (tower, group) — no waitlists in this change.
- New challenge *types* (see the `challenge-types` change) or presence gating (see the `presence-rules` change); this change only governs contention/locking.

## Decisions

- **`TowerLock` records an exclusive attempt window.** Fields `tower`, `team`, `started_at`, `expires_at`, plus a nullable `released_at` and a `release_reason` (`FINISHED` / `EXPIRED` / `CANCELLED`). The brief's core four fields are kept; `released_at` + `release_reason` are added so the model can distinguish a captured finish from an expiry without replaying the whole submission history. A lock is "active" when `released_at IS NULL AND expires_at > now`. Alternative considered: a boolean `is_active` flag — rejected because `expires_at` already encodes expiry and a flag would drift from the clock.
- **Locks are scoped per TeamGroup.** The active-lock constraint is one per `(tower, team.group)`, not one per tower globally. This mirrors `TeamTowerOwnership` (one active per tower per group) so a lock held by an EXPLORATORI team never blocks a SENIORI team that could legitimately co-own the same tower in its own group. Alternative considered: global per-tower lock — rejected because it would let one group's attempt freeze every other group out of a shared tower.
- **`tower_lock_mode` is a per-Game default + nullable per-Session override**, resolved by `Session.effective('tower_lock_mode')`, exactly like the Phase-10 pause/fail knobs. Choices: `FREE_FOR_ALL` (default) and `LOCK_ON_INITIATE`. `tower_lock_finish_minutes` (default e.g. 15) follows the same override pattern and is only consulted in `LOCK_ON_INITIATE`. Both new Session fields join `OVERRIDABLE_CONFIG_FIELDS`.
- **Three lifecycle verbs map to concrete endpoints.** *identify* → `POST /api/towers/{id}/identify/` returns the next challenge for the caller's team without side effects (thin wrapper over `get_next_challenge`); it is safe to call repeatedly. *initiate* → `POST /api/towers/{id}/initiate/` is the commitment point: under `LOCK_ON_INITIATE` it creates the `TowerLock` (or 409s if another team in the group holds an active lock); under `FREE_FOR_ALL` it is a no-op acknowledgement. *finish* → the existing `POST /api/team_tower_challenges/` submission. Alternative considered: overloading the submission POST to also lock — rejected because identify/initiate must be observable before a submission exists (e.g. to color the map and drive countdowns).
- **Finishing captures then releases.** On a confirmed `TeamTowerChallenge` under `LOCK_ON_INITIATE`, `assign_to_team` runs as today and the team's active lock is closed with `release_reason=FINISHED`. A confirmed finish from a team that does **not** hold the active lock is rejected while a lock is active (defense against a stale attempt). Under `FREE_FOR_ALL` there is no lock to check.
- **Expiry is enforced lazily and swept.** Any read that consults lock state treats `expires_at <= now` (and `released_at IS NULL`) as free, and a lightweight periodic sweep sets `released_at`/`release_reason=EXPIRED` so the DB doesn't accumulate phantom locks. Lazy-on-read guarantees correctness even if the sweep lags. Alternative considered: a scheduled job only — rejected because a delayed job would briefly block initiation on an already-expired lock.
- **Accrual is untouched by mode.** Capture still flows through `assign_to_team`, which closes the prior same-group `TeamTowerOwnership` window and opens the new one; zone control (and thus floating score) recomputes from those windows. Locking changes *eligibility to capture*, not the accrual, so both modes reconcile with the `scoring` capability by construction. A lock that expires without a confirmed finish never calls `assign_to_team`, so it opens no window and awards no `initial_bonus`.

## Risks / Trade-offs

- [A team locks a tower and abandons it, freezing others until expiry] → the finish deadline (`tower_lock_finish_minutes`) bounds the freeze; expiry auto-releases; runners tune the window; a `CANCELLED` release lets a team (or staff) voluntarily give up a lock early.
- [Clock skew between lazy-on-read and the sweep could double-release or race two initiations] → the partial-unique constraint on active `(tower, group)` locks makes a second concurrent initiate fail atomically; releases are idempotent (only set `released_at` when null).
- [Introducing `initiate` as a new required step could break existing FREE_FOR_ALL clients] → under `FREE_FOR_ALL`, `initiate` is optional and side-effect-free and the finish POST works without it, so current clients keep functioning unchanged.
- [Per-group locking is subtle and easy to mis-test] → explicit scenarios assert a lock in one group does not block another group, and that within a group a second team's initiate is refused.
- [Expired locks left in the table skew "active lock" queries] → all active-lock queries filter `released_at IS NULL AND expires_at > now`; the sweep is a tidy-up, not a correctness dependency.

## Migration Plan

1. Add `Game.tower_lock_mode` (default `FREE_FOR_ALL`) and `Game.tower_lock_finish_minutes` (default 15); add nullable `Session.tower_lock_mode` and `Session.tower_lock_finish_minutes`; extend `OVERRIDABLE_CONFIG_FIELDS` with both. Existing rows default to `FREE_FOR_ALL`, preserving today's behavior.
2. Add the `game.TowerLock` model with the partial-unique constraint on active locks per `(tower, team group)`; migrate schema. No data backfill needed (no locks exist historically).
3. Wire `identify` / `initiate` endpoints and the lock-holder check into the finish path; make all lock reads honor lazy expiry.
4. Add the expired-lock sweep (management command / periodic task) and register it.
5. Frontend: surface lock state + countdown in the player app and active locks in the staff app.
