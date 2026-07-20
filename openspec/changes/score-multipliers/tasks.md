## 1. Model & migration

- [ ] 1.1 Add `game.ScoreMultiplier` (`game` FK nullable, `session` FK nullable, `scope` [`TOWER`/`ZONE`/`GLOBAL`], `tower` FK nullable, `zone` FK nullable, `multiplier_type` [`MANUAL`/`SCHEDULED`/`RANDOM_BONUS`], `factor` Decimal default `1.0`, `is_active` default `True`, `window_start_offset`/`window_end_offset` DurationFields, `starts_at`/`ends_at` DateTimeFields, `label`, `created_by`, `created_at`).
- [ ] 1.2 Model validation: exactly one of `game`/`session` set; `scope=TOWER` requires `tower` (and no `zone`), `scope=ZONE` requires `zone` (and no `tower`), `scope=GLOBAL` requires neither; `factor > 0`; register admin.
- [ ] 1.3 Generate the additive migration; confirm no changes to existing scoring columns and no data migration.

## 2. Effective-factor resolver & scoring integration

- [ ] 2.1 Add `is_in_effect(at)` on `ScoreMultiplier`: `is_active` AND `at` inside the resolved window (offsets resolved against `session.start` for `SCHEDULED`; absolute `starts_at`/`ends_at` otherwise; unset bound = open).
- [ ] 2.2 Add `effective_tower_factor(session, tower, at)` and `effective_zone_factor(session, zone, at)`: product of in-effect multipliers matching `GLOBAL` or the specific target, across the union of `session`-owned and `session.game`-owned rows; return `1.0` when none.
- [ ] 2.3 Fold the zone factor into floating-score: `Zone.get_score`/`TeamZoneOwnership.get_score` return `base × effective_zone_factor(..., at=evaluation_time)`; the finalized (closed) window uses the factor at close time.
- [ ] 2.4 Fold the tower factor into `Tower.assign_to_team`: award `max(base_bonus × effective_tower_factor(..., at=capture_time), 1)` (base_bonus after any `decrease_initial_bonus` halving).

## 3. Authoring API (template SCHEDULED)

- [ ] 3.1 `GET/POST/PATCH/DELETE /api/staff/games/{id}/score-multipliers/` for `game`-owned multipliers; enforce `SCHEDULED` uses Session-relative offsets.
- [ ] 3.2 Deep-copy `game`-owned `ScoreMultiplier` rows when a Game is cloned (see the `game-authoring-roles` capability); never copy `session`-owned rows.

## 4. Live-control API (MANUAL / RANDOM_BONUS)

- [ ] 4.1 `POST /api/staff/sessions/{id}/score-multipliers/` to create a live `session`-owned `MANUAL` or `RANDOM_BONUS` multiplier (scope + target + factor + optional absolute window + `label`).
- [ ] 4.2 `POST .../score-multipliers/{id}/activate/` and `.../deactivate/` toggle a `MANUAL` multiplier's `is_active` live.
- [ ] 4.3 `GET /api/.../sessions/{id}/score-multipliers/active/` returns the multipliers in effect right now (factor, scope, target, `label`) for map/scoreboard consumption.

## 5. Frontend

- [ ] 5.1 Staff game editor: a schedule panel to author `SCHEDULED` multipliers (scope, factor, Session-relative window) with an overlap warning.
- [ ] 5.2 Staff session console: a live "boost" panel to drop `RANDOM_BONUS` at a tower/zone and to toggle `MANUAL` multipliers on/off.
- [ ] 5.3 Player app: read-only active-multiplier banner on the map/scoreboard (e.g. "Double points now", "Bonus at Old Tower").

## 6. Tests

- [ ] 6.1 Backward-compat: a session with zero `ScoreMultiplier` rows reproduces pre-change locked, floating, and initial-bonus values exactly (effective factor `1.0`).
- [ ] 6.2 Zone factor: a `GLOBAL 2×` in effect doubles floating points; a `ZONE 0.5×` halves them; a `GLOBAL 2×` composed with `ZONE 2×` yields `4×`.
- [ ] 6.3 Initial bonus: a `TOWER 2×` (and a composed `GLOBAL × TOWER`) multiplies the awarded `initial_bonus`; the `max(..., 1)` floor still holds.
- [ ] 6.4 Windows: `SCHEDULED` offset window is in effect only during its Session-relative interval; `MANUAL` respects live `is_active` toggles; `RANDOM_BONUS` respects its absolute window.
- [ ] 6.5 Scoping: a `game`-owned multiplier applies to every Session of that game and never to other games' sessions; a `session`-owned one applies only to that run.
- [ ] 6.6 Clone: cloning a Game copies its `game`-owned multipliers and not any `session`-owned ones.
- [ ] 6.7 API: authoring, live create, activate/deactivate, and the active-multiplier list endpoints behave and are permission-gated; ruff-clean and ≥80% branch coverage.
