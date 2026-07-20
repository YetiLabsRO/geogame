## 1. Models & migration

- [ ] 1.1 Add `Game.zone_conquest_rule` (`CharField` choices `ALL`/`MAJORITY`/`ANY`, default `MAJORITY`) and `Game.score_time_unit` (`CharField` choices `SECOND`/`MINUTE`/`HOUR`, default `MINUTE`).
- [ ] 1.2 Add nullable `Session.zone_conquest_rule` and `Session.score_time_unit` overrides (same choices, `null=True, blank=True`).
- [ ] 1.3 Add nullable `Zone.conquest_rule` override (same choices) and nullable `Tower.proximity_meters` (`PositiveIntegerField`, `null=True, blank=True`).
- [ ] 1.4 Generate one additive migration; confirm defaults reproduce current behavior (no data migration).

## 2. Effective-value helpers

- [ ] 2.1 `effective_conquest_rule(zone, session)` → `Zone.conquest_rule` if set, else `Session.zone_conquest_rule` if set, else `Session.game.zone_conquest_rule`.
- [ ] 2.2 `effective_proximity(tower, game)` → `Tower.proximity_meters` if set, else `game.proximity_meters`.
- [ ] 2.3 `effective_time_unit(session)` → `Session.score_time_unit` if set, else `Session.game.score_time_unit`.

## 3. Scoring engine

- [ ] 3.1 Replace the hardcoded majority computation with a dispatch on the effective conquest rule: `ALL` (team holds every active tower), `MAJORITY` (strict majority — retained verbatim), `ANY` (holds ≥1 active tower; tie-break most towers, then most recent capture); still computed per TeamGroup.
- [ ] 3.2 On a controller change, keep the existing open/close of `TeamZoneOwnership` (finalize floating into locked `score`, open a new window for the new controller if any).
- [ ] 3.3 Convert the zone score function to accrue over `units` = ownership-window duration expressed in the effective time unit; keep the four formula shapes unchanged so `MINUTE` yields `units == mins`.

## 4. API & serializers

- [ ] 4.1 Expose `zone_conquest_rule` and `score_time_unit` on the Game staff serializer (create/edit).
- [ ] 4.2 Expose nullable `zone_conquest_rule` and `score_time_unit` overrides on the Session staff serializer.
- [ ] 4.3 Expose `conquest_rule` on the Zone serializer and `proximity_meters` on the Tower serializer.
- [ ] 4.4 Route `GET /api/towers/` proximity filtering through `effective_proximity` so each tower uses its own radius.

## 5. Frontend (staff)

- [ ] 5.1 Add conquest-rule and time-unit selectors to the Game rule editor and the Session override panel, with an "effective rule" readout.
- [ ] 5.2 Add a conquest-rule override to the Zone editor and a proximity override to the Tower editor (blank = inherit).

## 6. Tests

- [ ] 6.1 Effective-value helpers: precedence for each of conquest rule (Zone > Session > Game), proximity (Tower > Game), and time unit (Session > Game), including the all-defaults path.
- [ ] 6.2 Conquest rules: `ALL` grants only when a team holds every active tower; `MAJORITY` matches the pre-change behavior; `ANY` grants on ≥1 tower with the most-towers-then-most-recent tie-break.
- [ ] 6.3 Time unit: `MINUTE` reproduces existing floating scores exactly (regression); `SECOND` and `HOUR` scale the window duration as expected before the formula is applied.
- [ ] 6.4 Proximity: a tower with its own `proximity_meters` is captured/filtered by that radius while sibling towers use the game-wide default.
- [ ] 6.5 Migration parity: an existing Game/Session with all defaults produces identical zone control and identical scores after the migration.
