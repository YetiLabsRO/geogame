## 1. Visibility config model & defaults

- [ ] 1.1 Add `Tower.discoverability` (nullable enum `HIDDEN` / `VISIBLE` / `FOG_REVEAL`) and `Tower.challenge_visibility` (nullable enum `HIDDEN_UNTIL_ARRIVAL` / `VISIBLE_ANYWHERE`); admin + migration.
- [ ] 1.2 Add `Zone.fog_reveal_coverage_pct` (nullable float 0–100); admin + migration.
- [ ] 1.3 Add `Game` defaults `tower_discoverability_default` (`VISIBLE`), `challenge_visibility_default` (`VISIBLE_ANYWHERE`), `fog_reveal_coverage_pct_default` (60), `reveal_other_teams_ownership` (True), each with a nullable per-`Session` override per the config pattern.
- [ ] 1.4 Add effective-value resolvers: `Tower.effective_discoverability(game)`, `Tower.effective_challenge_visibility(game)`, `Zone.effective_fog_reveal_pct(game)` (Session override → Game default → tower/zone null → game default).
- [ ] 1.5 Data migration backfilling existing Games to `VISIBLE` / `VISIBLE_ANYWHERE` / `reveal_other_teams_ownership=True`; leave per-tower/per-zone overrides null.

## 2. Discovery tracking model

- [ ] 2.1 Add `game.TowerDiscovery` (`session`, `team`, `tower`, `discovered_at`, `discovered_by`, `method` in `PROXIMITY` / `ZONE_ENTRY` / `ZONE_COVERAGE` / `ALWAYS_VISIBLE` / `STAFF`) with a unique constraint on `(session, team, tower)`; admin + migration.
- [ ] 2.2 Add `Session.visible_towers(team)` returning every `VISIBLE` tower plus every tower the team has a `TowerDiscovery` for, decoupled from ownership.
- [ ] 2.3 Ensure `TowerDiscovery` rows are append-only: never deleted on conquest by another team or on loss of ownership.

## 3. Discovery mechanism & evaluation

- [ ] 3.1 Implement `evaluate_discovery(session, team, point, user)`: reveal `HIDDEN` towers within their effective `proximity_meters`; reveal `FOG_REVEAL` towers when `point` lies inside their zone (`ZONE_ENTRY`).
- [ ] 3.2 Implement per-`(session, team, zone)` coverage accumulation (buffered union of visited positions ∩ zone ÷ zone area); reveal `FOG_REVEAL` towers when coverage exceeds `Zone.effective_fog_reveal_pct` (`ZONE_COVERAGE`), short-circuiting once crossed.
- [ ] 3.3 Consume `live-location` positions to drive `evaluate_discovery` when available; add `POST /api/discovery/ping/` (report position → return newly revealed towers) as the fallback source.
- [ ] 3.4 Add `GET /api/discovery/towers/` returning the caller team's discovered tower ids for the current Session.

## 4. Map/API visibility filtering (geographic-map)

- [ ] 4.1 Filter `GET /api/towers/` to `Session.visible_towers(team)`; omit undiscovered `HIDDEN`/`FOG_REVEAL` towers from the payload (queryset-level, not serializer-level).
- [ ] 4.2 Filter `GET /api/zones/` to hide a zone whose only towers are undiscovered `FOG_REVEAL` towers for a team that has not revealed it.
- [ ] 4.3 Apply `reveal_other_teams_ownership`: when False, colour only the caller's own control; when True, colour by all teams as today. Staff/omniscient callers bypass the visibility filter.

## 5. Player app UX (player-app)

- [ ] 5.1 Render only team-visible geometry; keep a discovered tower on the map after it is conquered by another team or becomes ownerless; honour `reveal_other_teams_ownership` in colouring.
- [ ] 5.2 Report position periodically (gated by location consent from `live-location`) and surface newly revealed towers with a discovery cue when `HIDDEN` towers pop up.
- [ ] 5.3 Render a fog-of-war overlay for games using `FOG_REVEAL`, progressively clearing covered area.
- [ ] 5.4 Tower detail: for `HIDDEN_UNTIL_ARRIVAL` conceal the challenge until inside the activation area; for `VISIBLE_ANYWHERE` show the challenge from afar but enable completion only inside the activation area.

## 6. Staff/creator config surfaces

- [ ] 6.1 Expose per-tower `discoverability` and `challenge_visibility`, per-zone `fog_reveal_coverage_pct`, and the per-game/per-session defaults + `reveal_other_teams_ownership` in the staff API and editor UI.

## 7. Tests

- [ ] 7.1 Backward-compat: an all-default game returns every active tower with full ownership colouring — payload identical to pre-change (regression).
- [ ] 7.2 `HIDDEN`: an undiscovered `HIDDEN` tower is absent from `GET /api/towers/`; after a proximity ping inside `proximity_meters` a `TowerDiscovery(method=PROXIMITY)` is created and the tower appears.
- [ ] 7.3 `FOG_REVEAL` zone entry: a position inside the zone reveals its `FOG_REVEAL` towers (`method=ZONE_ENTRY`).
- [ ] 7.4 `FOG_REVEAL` coverage: crossing `fog_reveal_coverage_pct` without entering reveals the towers (`method=ZONE_COVERAGE`); below threshold they stay hidden.
- [ ] 7.5 Persistence: a discovered tower stays visible to the discovering team after another team conquers it and after it becomes ownerless.
- [ ] 7.6 Challenge visibility: `HIDDEN_UNTIL_ARRIVAL` conceals the challenge from afar and reveals it inside the activation area; `VISIBLE_ANYWHERE` shows it from afar but blocks completion outside the area.
- [ ] 7.7 `reveal_other_teams_ownership=False` hides other teams' control but keeps the caller's own; `True` shows all.
- [ ] 7.8 Effective-value resolution: Session override beats Game default beats per-tower/per-zone null → Game default.
- [ ] 7.9 Coverage ≥80% branch coverage on the visibility/discovery module; ruff-clean; single quotes.
