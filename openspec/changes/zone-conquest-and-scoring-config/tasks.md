## 1. Models & migration

- [x] 1.1 Add `Game.zone_conquest_rule` (`CharField` choices `ALL`/`MAJORITY`/`ANY`, default `MAJORITY`) and `Game.score_time_unit` (`CharField` choices `SECOND`/`MINUTE`/`HOUR`, default `MINUTE`).
- [x] 1.2 Add nullable `Session.zone_conquest_rule` and `Session.score_time_unit` overrides (same choices, `null=True, blank=True`).
- [x] 1.3 Add nullable `Zone.conquest_rule` override (same choices) and nullable `Tower.proximity_meters` (`PositiveIntegerField`, `null=True, blank=True`).
- [x] 1.4 Generate one additive migration; confirm defaults reproduce current behavior (no data migration).

## 2. Effective-value helpers

- [x] 2.1 `effective_conquest_rule(zone, session)` → `Zone.conquest_rule` if set, else `Session.zone_conquest_rule` if set, else `Session.game.zone_conquest_rule`.
- [x] 2.2 `effective_proximity(tower, game)` → `Tower.proximity_meters` if set, else `game.proximity_meters`.
- [x] 2.3 `effective_time_unit(session)` → `Session.score_time_unit` if set, else `Session.game.score_time_unit`.

## 3. Scoring engine

- [x] 3.1 Replace the hardcoded majority computation with a dispatch on the effective conquest rule: `ALL` (team holds every active tower), `MAJORITY` (strict majority — retained verbatim), `ANY` (holds ≥1 active tower; tie-break most towers, then most recent capture); still computed per TeamGroup.
- [x] 3.2 On a controller change, keep the existing open/close of `TeamZoneOwnership` (finalize floating into locked `score`, open a new window for the new controller if any).
- [x] 3.3 Convert the zone score function to accrue over `units` = ownership-window duration expressed in the effective time unit; keep the four formula shapes unchanged so `MINUTE` yields `units == mins`.

## 4. API & serializers

- [x] 4.1 Expose `zone_conquest_rule` and `score_time_unit` on the Game staff serializer (create/edit).
- [x] 4.2 Expose nullable `zone_conquest_rule` and `score_time_unit` overrides on the Session staff serializer.
- [x] 4.3 Expose `conquest_rule` on the Zone serializer and `proximity_meters` on the Tower serializer.
- [x] 4.4 Route `GET /api/towers/` proximity filtering through `effective_proximity` so each tower uses its own radius.

## 5. Frontend (staff)

- [x] 5.1 Add conquest-rule and time-unit selectors to the Game rule editor and the Session override panel, with an "effective rule" readout.
- [x] 5.2 Add a conquest-rule override to the Zone editor and a proximity override to the Tower editor (blank = inherit).

## 6. Tests

- [x] 6.1 Effective-value helpers: precedence for each of conquest rule (Zone > Session > Game), proximity (Tower > Game), and time unit (Session > Game), including the all-defaults path.
- [x] 6.2 Conquest rules: `ALL` grants only when a team holds every active tower; `MAJORITY` matches the pre-change behavior; `ANY` grants on ≥1 tower with the most-towers-then-most-recent tie-break.
- [x] 6.3 Time unit: `MINUTE` reproduces existing floating scores exactly (regression); `SECOND` and `HOUR` scale the window duration as expected before the formula is applied.
- [x] 6.4 Proximity: a tower with its own `proximity_meters` is captured/filtered by that radius while sibling towers use the game-wide default.
- [x] 6.5 Migration parity: an existing Game/Session with all defaults produces identical zone control and identical scores after the migration.

## Implementation notes

Implemented together with `tower-zone-topology` on branch
`impl/zone-conquest-and-topology` (the two changes were reconciled: the
conquest-rule recompute is written topology-aware over `Tower.zones`).

- **Constants** live in `organize/models.py` (`CONQUEST_RULE_*`,
  `TIME_UNIT_*`, `TIME_UNIT_SECONDS`) next to the other shared config
  enums; `game/models.py` imports them. Both knobs were appended to
  `OVERRIDABLE_CONFIG_FIELDS`, so `Session.effective()` resolves them —
  no parallel mechanism.
- **Effective-value helpers** are module-level functions in
  `game/models.py`: `effective_conquest_rule(zone, session=None, game=None)`,
  `effective_proximity(tower, game)`, `effective_time_unit(session)`.
  `effective_conquest_rule` accepts an optional `game` fallback because
  the recompute may have no Session context for a TeamGroup (nobody in
  the group holds a tower); it then uses the group's Game default.
- **Session resolution during recompute** (`Tower._resolve_rule_session`):
  the capturing team's Session when the group is the capturer's own,
  else the Session of any current holder in the group, else None →
  Game default. Documented risk: two RUNNING Sessions of the same Game
  with *different* conquest-rule overrides sharing one TeamGroup could
  disagree; in practice teams of one group play in one Session.
- **MAJORITY branch retained verbatim**: the historical computation is
  most-towers-wins *with ties keeping every tied team as a controller*
  (plurality, not strict majority). The spec calls it strict majority;
  parity with shipped behavior won (all pre-change tests pass
  unchanged). `ALL`/`ANY` produce a unique controller or none; `ANY`
  tie-breaks by most towers then most recent `TeamTowerOwnership.timestamp_start`.
- **Score time unit** is applied inside `Zone.get_score(seconds, time_unit)`;
  the four formula bodies now take `units` (already divided). MINUTE
  default ⇒ `units == mins` ⇒ byte-identical historical scores
  (regression-tested). `TeamZoneOwnership.get_score` resolves the unit
  via the owning team's Session.
- **Proximity**: capture validation (`TeamTowerChallengeSerializer`),
  the tower-state endpoint payload, and `GET /api/towers/` filtering all
  route through `effective_proximity`. The towers-list filter keeps the
  historical `min(accuracy, radius)` shape but the 50 m cap is now the
  per-tower effective radius (game default when unset), computed in SQL
  via `Coalesce`/`Least` + `ST_DistanceSphere`.
- **Migrations**: `organize/0018_game_session_conquest_scoring_knobs`
  (Game defaults + Session overrides) and
  `game/0026_zone_conquest_rule_tower_proximity` (Zone override + Tower
  radius). Purely additive, no data migration.
- Frontend: conquest-rule + time-unit selects on the Games rules panel
  and the Session overrides panel (with an effective-value readout
  backed by a new `StaffApiService.getGame()`); Zone editor gained an
  Inherit/ALL/MAJORITY/ANY select; Tower editor a proximity override
  input (blank = inherit). Both staff and player apps build.
- **Merge-conflict hotspots**: `organize/models.py` (constants +
  `OVERRIDABLE_CONFIG_FIELDS` + Game/Session fields), `game/models.py`
  (heavily rewritten recompute), `game/admin_api.py` (Game/Session
  serializer field lists), `frontend/projects/shared/src/lib/staff-api.service.ts`,
  `games.component.ts`, `session-detail.component.ts`.
