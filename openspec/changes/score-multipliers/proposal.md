## Why

Every game today scores a tower or zone at a fixed worth: an `initial_bonus` on capture and a `score_type` curve for held-zone floating points. Organisers want to make certain moments and certain places matter more — a "happy hour" where all points double, a scripted arc (hour 1 normal, hour 2 double, hour 3 half), or a surprise "bonus points at tower X right now" that an admin drops live. This is a **scoring-layer** feature: it applies to every game type, not a new mode. This change introduces a `ScoreMultiplier` — a factor applied to a tower, a zone, or the whole game — and folds that factor into floating-score and initial-bonus computation. With no multipliers configured the factor is `1.0` everywhere, so existing scoring is byte-for-byte unchanged.

## What Changes

- Introduce a `game.ScoreMultiplier` model: a **spatial scope** (`TOWER`, `ZONE`, or `GLOBAL`), a decimal **factor** (e.g. `2.0` = double, `0.5` = half), a **type** (`MANUAL`, `SCHEDULED`, `RANDOM_BONUS`), a **window/schedule**, and an **active flag**. It is owned by either a `Game` (template-level, applies to every Session of that game — typically pre-scripted `SCHEDULED` arcs) or a single `Session` (run-level, typically `MANUAL` and `RANDOM_BONUS` drops).
- Add an effective-factor resolver: for a given tower or zone in a given Session at a given time, the factor is the product of every in-effect multiplier whose scope matches (global × zone × tower), defaulting to `1.0` when none apply.
- Fold the factor into scoring: a held zone's floating points become `base_score × effective_zone_factor`; a captured tower's `initial_bonus` becomes `base_bonus × effective_tower_factor` (still floored at 1).
- Add types: `MANUAL` (an admin toggles `is_active` live), `SCHEDULED` (a window expressed as an offset from Session start — e.g. hour 2), and `RANDOM_BONUS` (created on the fly with an absolute live window and a player-facing label).
- Staff/creator API to author template `SCHEDULED` multipliers; runner API to create and toggle live `MANUAL`/`RANDOM_BONUS` multipliers on a running Session; the set of currently-in-effect multipliers is exposed so the map and scoreboard can announce "double points now" or "bonus at tower X".

## Capabilities

### New Capabilities
- `score-multipliers`: time- and place-based scoring modifiers (`MANUAL` / `SCHEDULED` / `RANDOM_BONUS`) that multiply a tower's or zone's worth by a configurable factor, applied across all game types.

### Modified Capabilities
- `scoring`: floating-score and initial-bonus computation multiply the base value by the target's effective score multiplier factor (defaulting to `1.0`).

## Impact

- **Models**: new `game.ScoreMultiplier` (nullable `game` FK and nullable `session` FK — exactly one set; `scope`; nullable `tower`/`zone` FKs; `multiplier_type`; `factor`; `is_active`; relative `window_start_offset`/`window_end_offset` and absolute `starts_at`/`ends_at`; `label`; `created_by`/`created_at`). No change to existing scoring columns.
- **APIs**: `GET/POST/PATCH/DELETE /api/staff/games/{id}/score-multipliers/` (template SCHEDULED); `POST /api/staff/sessions/{id}/score-multipliers/` plus `.../activate/` and `.../deactivate/` (live control); `GET /api/.../sessions/{id}/score-multipliers/active/` (currently-in-effect list for map/scoreboard).
- **Frontend**: staff app gains a multiplier scheduler on the game editor and a live "boost" panel on the session console; player app map/scoreboard show active-multiplier banners (read-only).
- **Migrations/other**: one additive migration creating `ScoreMultiplier`; no data migration needed because the default (no rows) reproduces current scoring exactly.
