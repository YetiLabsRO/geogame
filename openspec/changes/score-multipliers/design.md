## Context

Scoring in the shipped game has two channels (see the `scoring` capability): a **locked** component (cumulative `Team.score`, credited instantly — `initial_bonus` on tower capture, plus finalized zone windows) and a **floating** component (live-computed points from currently-held zones, via `Zone.get_score(seconds)` and one of four `score_type` curves). Both are fixed per tower/zone. Organisers want time- and place-based emphasis: scripted "double points in hour 2", live admin-triggered boosts, and surprise bonuses at a named tower. Because this reshapes *worth*, it must apply uniformly to every game type rather than being a mode. The design goal is a single multiplication factor folded into exactly the two places worth is computed, defaulting to `1.0` so nothing changes until an organiser opts in.

## Goals / Non-Goals

**Goals:**
- One `ScoreMultiplier` model expressing scope (tower / zone / global), factor, type, window, and active flag.
- Fold a single effective factor into floating-score and initial-bonus computation, and nowhere else.
- Support the three authoring stories: `MANUAL` (admin live toggle), `SCHEDULED` (pre-scripted by Session-relative window), `RANDOM_BONUS` (dropped on the fly at a place).
- Preserve current scoring exactly when no multiplier is configured (effective factor `1.0`).
- Apply across all game types — this is a scoring-layer feature, not a mode.

**Non-Goals:**
- Time-weighted integration of a *changing* factor across a single long zone-ownership window (piecewise integral). This change applies the factor **in effect at the evaluation instant** to the whole computed value; sub-window integration is a possible later refinement.
- Additive point bonuses, per-team or per-TeamGroup multipliers, or multipliers that change a zone's control rule — factor is a pure multiplication on worth, equal for every team.
- Notification delivery mechanics for "double points now" banners — surfacing the active-multiplier list is in scope; push transport belongs to the `realtime-and-notifications` change.

## Decisions

- **`ScoreMultiplier` lives in the `game` app** next to the geometry and scoring it modifies. It carries a nullable `game` FK (organize.Game) and a nullable `session` FK (organize.Session); **exactly one** is set. A `game`-owned multiplier applies to every Session of that game (the template default, typically a `SCHEDULED` arc); a `session`-owned one applies to that single run (typically `MANUAL`/`RANDOM_BONUS`). This mirrors the "Game defaults + per-Session overrides" config pattern used elsewhere, generalised from a scalar knob to a set of rows. The effective set for a Session is the union of its Game's multipliers and its own.
- **Spatial scope is an explicit `scope` field** (`TOWER`/`ZONE`/`GLOBAL`) plus nullable `tower`/`zone` FKs: `TOWER` requires `tower`, `ZONE` requires `zone`, `GLOBAL` requires neither and applies to all towers and zones. Alternative considered: derive scope from which FK is non-null — rejected because an explicit field validates cleanly and reads unambiguously in the API.
- **Factors compose multiplicatively across scopes.** For a target tower, `effective_tower_factor = ∏ factors of in-effect multipliers matching (GLOBAL) or (TOWER, this tower)`. For a zone, `∏` over `(GLOBAL)` or `(ZONE, this zone)`. So a global `2×` happy hour and a `2×` bonus on tower X compose to `4×` at tower X. Alternative considered: most-specific-wins (tower overrides global) — rejected because "a surprise bonus stacks on happy hour" is the intuitive product model, and it keeps the neutral element a clean `1.0`.
- **The factor is applied at the evaluation instant, not integrated.** Floating points for a held zone are `Zone.get_score(seconds) × effective_zone_factor(session, zone, at=now)`; when the ownership window closes and is finalized into locked score, the factor at close time is used. `initial_bonus` is multiplied by `effective_tower_factor(session, tower, at=capture_time)`, then floored at 1: `max(base_bonus × factor, 1)`. This keeps the change small and the semantics legible for players ("it's hour 2, points are doubled").
- **Windows are typed to the multiplier type.** `SCHEDULED` uses Session-relative offsets (`window_start_offset`, `window_end_offset` as durations from `Session.start`) so the same template arc replays on every run regardless of wall-clock. `MANUAL`/`RANDOM_BONUS` use absolute `starts_at`/`ends_at` (or none, for an open-ended manual toggle). A multiplier is **in effect** at time `T` iff `is_active` is true AND `T` falls inside its resolved window (an unset bound is open on that side). `MANUAL` typically leaves the window open and is gated purely by `is_active`, which the admin toggles live.
- **Default is `1.0` and byte-for-byte compatible.** With no `ScoreMultiplier` rows the resolver returns `1.0`, and `base × 1.0` equals the current value (the `max(..., 1)` floor is unchanged), so no data migration and no behavioural drift.
- **Active-multiplier list is exposed read-only.** A resolver endpoint returns the multipliers in effect for a Session right now (factor, scope, target, label) so the map and scoreboard can announce them; transport (poll vs push) is out of scope here.

## Risks / Trade-offs

- [Applying the factor at the evaluation instant rather than integrating means a zone held across a `SCHEDULED` boundary is scored entirely at the closing factor] → Documented as a Non-Goal; acceptable because floating score recomputes continuously (players see the current factor live) and organisers script short windows. A piecewise integral can be added later without changing the model.
- [Multiplicative composition could produce surprising large factors if many multipliers overlap] → The resolver is deterministic and the active-multiplier list is surfaced so admins see exactly what is stacking; factor is validated `> 0`; UI warns when creating an overlapping global multiplier.
- [`MANUAL` toggles are live mutations to scoring mid-run] → Only the `is_active` flag toggles; historical finalized locked score is never retroactively rewritten, so toggling affects only worth accrued from that instant forward.
- [Template `SCHEDULED` multipliers reference repository towers/zones shared across games] → Scope resolution is always evaluated within a Session (`session.game`), so a multiplier only ever affects the runs of the game that owns it; shared geometry does not leak boosts across games.
- [Cloning a Game (see the `game-authoring-roles` capability) must carry its `SCHEDULED` multipliers] → Clone deep-copies `game`-owned `ScoreMultiplier` rows; `session`-owned rows are never copied (they belong to a finished run).

## Migration Plan

1. Add the `game.ScoreMultiplier` model and one additive migration. No existing column changes; no data migration (absence of rows == current behaviour).
2. Add the `effective_tower_factor` / `effective_zone_factor` resolver in the `game` app and route `Tower.assign_to_team` (bonus) and `Zone.get_score` / floating-score computation through it.
3. Add staff authoring API for `game`-owned `SCHEDULED` multipliers and runner live-control API for `session`-owned `MANUAL`/`RANDOM_BONUS` multipliers, plus the active-multiplier resolver endpoint.
4. Wire clone (game-authoring-roles) to deep-copy `game`-owned multipliers.
5. Regression test: a session with zero multipliers reproduces pre-change scores exactly.
