## Context

Sessions are one live run of a Game (see the `sessions` and `game-configuration` specs). Ownership records (`TeamTowerOwnership`, `TeamZoneOwnership`) hang off Team and carry `timestamp_start` / `timestamp_end`; floating score is computed from the open window's duration (see `scoring`). Today, proximity and cooloff are read from per-Game config, and a rejected submission only triggers a cooloff. This change layers two opt-in feature sets on top of that machinery, spanning the `game` and `organize` apps.

## Goals / Non-Goals

**Goals:**
- Let staff pause/resume a Session cleanly across day cut-offs, with configurable freezing of scoring, restore-on-resume of ownerships, and submission handling.
- Let staff attach configurable, combinable consequences to challenge failure.
- Preserve current behavior by default — every new knob defaults to a no-op.

**Non-Goals:**
- Automatic or scheduled pausing (all pause/resume is staff-triggered).
- `SessionGroup` / shared clocks across sessions (explicitly out of scope; `pause_all` operates per-Game for now).
- Any cross-team interaction of failure penalties.

## Decisions

- **PauseWindow lives in the `game` app**, not `organize`, because it reads and mutates the ownership records (`TeamTowerOwnership` / `TeamZoneOwnership`) that live there. A Session is "paused" iff it has a window with `ended_at IS NULL` — derived state, no denormalized boolean to keep in sync.
- **Config knobs live on `Game` as defaults with nullable per-`Session` overrides**, resolved by an "effective value" helper (Session override wins, else Game default). This mirrors how `proximity_meters` / `cooloff_minutes` already resolve and keeps a single override pattern across both feature sets. Alternative considered: knobs only on Session — rejected, because most events want one policy for all runs of a Game.
- **Frozen floating score** is implemented by evaluating `Team.floating_score()` as of `window.started_at` while a window is open and freezing is enabled, rather than mutating stored rows. This keeps the pause reversible and avoids double-counting on resume.
- **Restore-on-resume** snapshots the `(team, tower)` and `(team, zone)` pairs open at pause time onto the window, then reopens fresh ownership rows with `timestamp_start = resume_time`. Closing at `timestamp_end = window.started_at` ensures no score accrues during the pause.
- **Consecutive-fail tracking** is per `(team, tower)`. Prefer a small dedicated model (`consecutive_fails`, `last_failed_at`, `locked_until`) over deriving from the `TeamTowerChallenge` history on every read, because cooloff scaling and lockout are read on the hot submission path. `fail_counter_reset` semantics decide when the counter zeroes.

## Risks / Trade-offs

- [Resume reopening ownerships could conflict with captures that happened while `pause_rejects_submissions=False`] → On resume, reconcile against current ownership before reopening; a held-then-captured tower should not be handed back to the pre-pause owner.
- [Effective-value resolution scattered across serializers/model methods] → Centralize in one helper per knob and cover with tests where a per-Session override beats the Game default.
- [Point penalty and counter updates race under concurrent reviews] → Apply penalties and counter mutations atomically (select-for-update / F-expressions), clamped to ≥ 0.
- [Difficulty rollback interacts with next-challenge selection] → Rollback only shifts the difficulty bucket the existing selection algorithm draws from; it does not replace the algorithm.

## Migration Plan

- Additive migrations only: new `PauseWindow` model, new nullable config fields on `Game` and `Session`, new consecutive-fail model. No backfill needed — defaults are no-ops, so migrated games behave exactly as before.
- Ship model + config + endpoints first, then wire scoring/submission reads, then staff UI. Rollback is dropping the additive migrations; no existing data is rewritten.
