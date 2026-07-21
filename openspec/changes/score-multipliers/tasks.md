## 1. Model & migration

- [x] 1.1 Add `game.ScoreMultiplier` (`game` FK nullable, `session` FK nullable, `scope` [`TOWER`/`ZONE`/`GLOBAL`], `tower` FK nullable, `zone` FK nullable, `multiplier_type` [`MANUAL`/`SCHEDULED`/`RANDOM_BONUS`], `factor` Decimal default `1.0`, `is_active` default `True`, `window_start_offset`/`window_end_offset` DurationFields, `starts_at`/`ends_at` DateTimeFields, `label`, `created_by`, `created_at`).
- [x] 1.2 Model validation: exactly one of `game`/`session` set; `scope=TOWER` requires `tower` (and no `zone`), `scope=ZONE` requires `zone` (and no `tower`), `scope=GLOBAL` requires neither; `factor > 0`; register admin.
- [x] 1.3 Generate the additive migration; confirm no changes to existing scoring columns and no data migration.

## 2. Effective-factor resolver & scoring integration

- [x] 2.1 Add `is_in_effect(at)` on `ScoreMultiplier`: `is_active` AND `at` inside the resolved window (offsets resolved against `session.start` for `SCHEDULED`; absolute `starts_at`/`ends_at` otherwise; unset bound = open).
- [x] 2.2 Add `effective_tower_factor(session, tower, at)` and `effective_zone_factor(session, zone, at)`: product of in-effect multipliers matching `GLOBAL` or the specific target, across the union of `session`-owned and `session.game`-owned rows; return `1.0` when none.
- [x] 2.3 Fold the zone factor into floating-score: `Zone.get_score`/`TeamZoneOwnership.get_score` return `base × effective_zone_factor(..., at=evaluation_time)`; the finalized (closed) window uses the factor at close time.
- [x] 2.4 Fold the tower factor into `Tower.assign_to_team`: award `max(base_bonus × effective_tower_factor(..., at=capture_time), 1)` (base_bonus after any `decrease_initial_bonus` halving).

## 3. Authoring API (template SCHEDULED)

- [x] 3.1 `GET/POST/PATCH/DELETE /api/staff/games/{id}/score-multipliers/` for `game`-owned multipliers; enforce `SCHEDULED` uses Session-relative offsets.
- [x] 3.2 Deep-copy `game`-owned `ScoreMultiplier` rows when a Game is cloned (see the `game-authoring-roles` capability); never copy `session`-owned rows.

## 4. Live-control API (MANUAL / RANDOM_BONUS)

- [x] 4.1 `POST /api/staff/sessions/{id}/score-multipliers/` to create a live `session`-owned `MANUAL` or `RANDOM_BONUS` multiplier (scope + target + factor + optional absolute window + `label`).
- [x] 4.2 `POST .../score-multipliers/{id}/activate/` and `.../deactivate/` toggle a `MANUAL` multiplier's `is_active` live.
- [x] 4.3 `GET /api/.../sessions/{id}/score-multipliers/active/` returns the multipliers in effect right now (factor, scope, target, `label`) for map/scoreboard consumption.

## 5. Frontend

- [x] 5.1 Staff game editor: a schedule panel to author `SCHEDULED` multipliers (scope, factor, Session-relative window) with an overlap warning.
- [x] 5.2 Staff session console: a live "boost" panel to drop `RANDOM_BONUS` at a tower/zone and to toggle `MANUAL` multipliers on/off.
- [x] 5.3 Player app: read-only active-multiplier banner on the map/scoreboard (e.g. "Double points now", "Bonus at Old Tower").

## 6. Tests

- [x] 6.1 Backward-compat: a session with zero `ScoreMultiplier` rows reproduces pre-change locked, floating, and initial-bonus values exactly (effective factor `1.0`).
- [x] 6.2 Zone factor: a `GLOBAL 2×` in effect doubles floating points; a `ZONE 0.5×` halves them; a `GLOBAL 2×` composed with `ZONE 2×` yields `4×`.
- [x] 6.3 Initial bonus: a `TOWER 2×` (and a composed `GLOBAL × TOWER`) multiplies the awarded `initial_bonus`; the `max(..., 1)` floor still holds.
- [x] 6.4 Windows: `SCHEDULED` offset window is in effect only during its Session-relative interval; `MANUAL` respects live `is_active` toggles; `RANDOM_BONUS` respects its absolute window.
- [x] 6.5 Scoping: a `game`-owned multiplier applies to every Session of that game and never to other games' sessions; a `session`-owned one applies only to that run.
- [x] 6.6 Clone: cloning a Game copies its `game`-owned multipliers and not any `session`-owned ones.
- [x] 6.7 API: authoring, live create, activate/deactivate, and the active-multiplier list endpoints behave and are permission-gated; ruff-clean and ≥80% branch coverage.

## Implementation notes

- **Deviation from task 1.1 wording:** `factor` is a `FloatField` (not Decimal) —
  the scoring pipeline (`Zone.get_score`, `initial_bonus` math) is float/int
  arithmetic already, so a Decimal would be coerced at every use. Validation
  still enforces `factor > 0`; wire shape is a JSON number.
- **New files:** `game/multipliers_api.py` (all six endpoints + the
  `active_multiplier_payload` wire helper), migration
  `game/migrations/0026_score_multiplier.py` (additive only; forks from
  `0025_merge_20260721_0017` — renumbering at merge is expected).
- **Scoring integration points:** `Tower.assign_to_team` multiplies the
  post-halving bonus and keeps the `max(..., 1)` floor;
  `TeamZoneOwnership.get_score(ref_time)` applies
  `effective_zone_factor(..., at=ref_time)` so open windows use "now" and
  finalized windows use the close instant. No other scoring path touched;
  zero rows ⇒ factor exactly `1.0` (byte-for-byte compat, tested).
- **Submission serializer untouched** — no new checks were inserted into
  `TeamTowerChallengeSerializer.validate`.
- **Permissions:** template authoring mutations require `Game.can_edit`
  (creator-only, mirroring the challenge-bank rule); session live-control is
  `IsAdminUser`; the active list is staff OR a member of that session.
  The session list endpoint returns the union of Session- and Game-owned rows
  so the console sees the whole picture; activate/deactivate accepts any row
  reachable from the session (its own or its Game's).
- **Scoreboard payload** (`organize/api.py` `SessionScoreboardView`) now carries
  `active_multipliers` for scoreboard badges.
- **Frontend:** staff `score-multipliers-panel.component.ts` (SCHEDULED
  authoring, embedded as an expandable "Multipliers" row on the Games page,
  client-side non-blocking overlap warning); "Score boosts" card on the staff
  session console (union table, activate/deactivate, drop MANUAL/RANDOM_BONUS
  with optional duration → absolute `ends_at`); player map polls the active
  endpoint every 60 s for the boost banner; player session scoreboard shows
  active-boost badges from the scoreboard payload. Offset windows are edited
  as whole minutes and converted to/from Django duration strings
  (`minutesToDuration`/`durationToMinutes` in the panel component). Tower/zone
  pickers reuse the repository usage refs (`AdminTower.games`) to offer only
  geometry reachable by the game. Both apps build clean
  (`ng build staff|player --configuration development`).
- **Merge conflict hotspots:** `game/models.py` (new model + resolver at the
  end, factor folds in `Tower.assign_to_team` / `TeamZoneOwnership.get_score`),
  `organize/models.py` (`Game.clone` — new multiplier-copy block after the
  challenge remap), `geogame/urls.py` (new nested paths before the admin
  router include), `organize/api.py` (scoreboard payload), `game/admin.py`,
  `game/tests.py` (appended section), migration number `0026`, and
  `frontend/projects/shared/src/lib/{game,staff}-api.service.ts` +
  `staff admin/{games,session-detail}.component.ts`.
- **Verification:** `manage.py test game organize` — 460 tests OK (412
  baseline + 48 new); ruff clean; `makemigrations --check` clean. Coverage
  of the new code: `game/multipliers_api.py` 100% (incl. branches),
  `game/models.py` 93%. Note the CI gate invocation is
  `coverage run manage.py test game organize` (both apps) — running only
  `test game` under coverage reports ~75% because organize/api.py is then
  never exercised; that is an artifact of the invocation, not this change.
