## Context

The shipped `scoring` capability hardcodes three things. Zone control is granted to the team holding a **strict majority** of a zone's active towers (`Majority-rule zone control`). Capture proximity is a single game-wide `proximity_meters` (default 50) read from the current Session's Game. And the zone score functions are defined over `mins`, the ownership-window duration in minutes. Different events want different rules on the **same** map: an "all towers" siege variant, a "one flag" skirmish, per-tower radii (a tiny statue vs a wide plaza), and re-cadenced scoring (fast sprint vs multi-day campaign). This change generalizes all three into configuration, reusing the codebase's `Game`-default / `Session`-or-object-override pattern so existing games are byte-for-byte unchanged.

## Goals / Non-Goals

**Goals:**
- Zone conquest is a first-class rule enum (`ALL` / `MAJORITY` / `ANY`) with `MAJORITY` as the default, configurable per Zone over a per-Game default and per-Session override.
- Capture proximity is overridable per Tower, falling back to the existing game-wide default.
- The zone score functions accrue per a configurable time unit (`SECOND` / `MINUTE` / `HOUR`), with `MINUTE` as the default so existing formulas are unchanged.
- Every default preserves current behavior: no data migration, identical scores and identical zone control for existing Sessions.

**Non-Goals:**
- Changing the four score-function shapes (`LINEAR` / `LOGARITHMIC` / `EXPONENTIAL` / `BONUS`) — only the time base they read.
- Per-zone or per-tower time-unit overrides — the time unit is a session-wide scoring cadence (Game default + Session override only).
- The `Tower.zone` single-FK → M2M topology change (see the `tower-zone-topology` change) and the repository/Collection refactor (see `points-repository-and-collections`) — this change is orthogonal and layers only on the current field shape.
- Any new proximity strategy beyond a radius in meters.

## Decisions

- **Conquest rule as a shared enum on `Game`, `Session`, and `Zone`.** `Game.zone_conquest_rule` (non-null, default `MAJORITY`) is the per-Game default; `Session.zone_conquest_rule` (nullable) overrides it for a run; `Zone.conquest_rule` (nullable) is the most-specific per-object override. Effective rule for a `(zone, session)` = `Zone.conquest_rule` if set, else `Session.zone_conquest_rule` if set, else `Game.zone_conquest_rule`. Alternative considered: a single flag per Game only — rejected because the product wants mixed rules on one map (a "hold-all" citadel next to "any-tower" outposts).
- **`ANY` needs a tie-break; `ALL`/`MAJORITY` do not.** Under `MAJORITY` at most one team can hold a strict majority, and under `ALL` at most one team can hold every tower, so both yield a unique controller or none. Under `ANY` several teams in the same TeamGroup may each hold ≥1 tower; the zone goes to the team holding the **most** active towers, ties broken by the **most recent** tower capture. This keeps `ANY` deterministic and reuses ownership timestamps already recorded.
- **Conquest is still computed per TeamGroup**, exactly as today; only the "does this team win the zone" predicate is swapped by the effective rule. The open/close of `TeamZoneOwnership` on a controller change (finalizing floating score into locked `score`) is unchanged.
- **Per-tower proximity override, game-wide fallback.** `Tower.proximity_meters` (nullable `PositiveIntegerField`) overrides the Game's game-wide `proximity_meters` for that tower only; unset falls back to the game default. No per-Session proximity override — proximity is a physical property of the point, best expressed on the Tower. Effective radius = `Tower.proximity_meters` if set, else `Game.proximity_meters`.
- **Time unit as a `Game` default + `Session` override, applied in the score function.** `Game.score_time_unit` (default `MINUTE`), `Session.score_time_unit` (nullable override). The score function computes the window duration, converts it to the effective unit (`units`), and applies the same formula. Because the formulas are unchanged and `MINUTE` yields `units == mins`, every existing game scores identically. Alternative considered: rescaling the formula constants per unit — rejected because it changes results and complicates the requirement; converting the time base is the minimal, behavior-preserving change.
- **Additive migration, no backfill.** All new fields are additive; non-null fields take defaults that reproduce current behavior, nullable fields default to `NULL` (fall through to the default). No data migration is required.

## Risks / Trade-offs

- [`ANY` with several teams holding towers could look arbitrary to players] → the deterministic tie-break (most towers, then most recent capture) is specified and covered by a test; the staff UI documents the rule.
- [Changing the score function's time base could silently alter scores] → the `MINUTE` default makes `units == mins`; a regression test asserts identical floating scores for a migrated game, and a test asserts `SECOND`/`HOUR` scale the duration as expected.
- [Effective-value resolution scattered across the scoring engine and serializers] → centralize each in a single helper (`effective_conquest_rule(zone, session)`, `effective_proximity(tower, game)`, `effective_time_unit(session)`) and route all call sites through it; unit-test each helper's precedence.
- [A per-Zone rule plus a per-Session override could confuse operators about which wins] → the precedence (Zone > Session > Game) is stated as a requirement and surfaced in the staff editor as an "effective rule" readout.

## Migration Plan

1. Add fields: `Game.zone_conquest_rule` (choices `ALL`/`MAJORITY`/`ANY`, default `MAJORITY`), `Game.score_time_unit` (choices `SECOND`/`MINUTE`/`HOUR`, default `MINUTE`), nullable `Session.zone_conquest_rule` and `Session.score_time_unit`, nullable `Zone.conquest_rule`, nullable `Tower.proximity_meters`. One additive schema migration.
2. Add the three effective-value helpers and route the scoring engine and proximity filter through them.
3. Swap the zone-control recomputation to dispatch on the effective conquest rule (majority path is retained verbatim as the `MAJORITY` branch).
4. Convert the score-function time base to the effective unit.
5. No data migration: defaults reproduce current behavior; a regression test confirms parity for a pre-existing game.
