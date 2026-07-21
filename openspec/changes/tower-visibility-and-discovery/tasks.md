## 1. Visibility config model & defaults

- [x] 1.1 Add `Tower.discoverability` (nullable enum `HIDDEN` / `VISIBLE` / `FOG_REVEAL`) and `Tower.challenge_visibility` (nullable enum `HIDDEN_UNTIL_ARRIVAL` / `VISIBLE_ANYWHERE`); admin + migration.
- [x] 1.2 Add `Zone.fog_reveal_coverage_pct` (nullable float 0–100); admin + migration.
- [x] 1.3 Add `Game` defaults `tower_discoverability_default` (`VISIBLE`), `challenge_visibility_default` (`VISIBLE_ANYWHERE`), `fog_reveal_coverage_pct_default` (60), `reveal_other_teams_ownership` (True), each with a nullable per-`Session` override per the config pattern.
- [x] 1.4 Add effective-value resolvers: `Tower.effective_discoverability(game)`, `Tower.effective_challenge_visibility(game)`, `Zone.effective_fog_reveal_pct(game)` (Session override → Game default → tower/zone null → game default).
- [x] 1.5 Data migration backfilling existing Games to `VISIBLE` / `VISIBLE_ANYWHERE` / `reveal_other_teams_ownership=True`; leave per-tower/per-zone overrides null. (Performed by the `AddField` defaults in `organize/0021` — Django writes the default into every existing row at migrate time; a separate RunPython pass would be a no-op.)

## 2. Discovery tracking model

- [x] 2.1 Add `game.TowerDiscovery` (`session`, `team`, `tower`, `discovered_at`, `discovered_by`, `method` in `PROXIMITY` / `ZONE_ENTRY` / `ZONE_COVERAGE` / `ALWAYS_VISIBLE` / `STAFF`) with a unique constraint on `(session, team, tower)`; admin + migration.
- [x] 2.2 Add `Session.visible_towers(team)` returning every `VISIBLE` tower plus every tower the team has a `TowerDiscovery` for, decoupled from ownership.
- [x] 2.3 Ensure `TowerDiscovery` rows are append-only: never deleted on conquest by another team or on loss of ownership.

## 3. Discovery mechanism & evaluation

- [x] 3.1 Implement `evaluate_discovery(session, team, point, user)`: reveal `HIDDEN` towers within their effective `proximity_meters`; reveal `FOG_REVEAL` towers when `point` lies inside their zone (`ZONE_ENTRY`).
- [x] 3.2 Implement per-`(session, team, zone)` coverage accumulation (buffered union of visited positions ∩ zone ÷ zone area); reveal `FOG_REVEAL` towers when coverage exceeds `Zone.effective_fog_reveal_pct` (`ZONE_COVERAGE`), short-circuiting once crossed.
- [x] 3.3 Consume `live-location` positions to drive `evaluate_discovery` when available; add `POST /api/discovery/ping/` (report position → return newly revealed towers) as the fallback source.
- [x] 3.4 Add `GET /api/discovery/towers/` returning the caller team's discovered tower ids for the current Session.

## 4. Map/API visibility filtering (geographic-map)

- [x] 4.1 Filter `GET /api/towers/` to `Session.visible_towers(team)`; omit undiscovered `HIDDEN`/`FOG_REVEAL` towers from the payload (queryset-level, not serializer-level).
- [x] 4.2 Filter `GET /api/zones/` to hide a zone whose only towers are undiscovered `FOG_REVEAL` towers for a team that has not revealed it.
- [x] 4.3 Apply `reveal_other_teams_ownership`: when False, colour only the caller's own control; when True, colour by all teams as today. Staff/omniscient callers bypass the visibility filter.

## 5. Player app UX (player-app)

- [x] 5.1 Render only team-visible geometry; keep a discovered tower on the map after it is conquered by another team or becomes ownerless; honour `reveal_other_teams_ownership` in colouring. (Server-side filtering means the map only ever receives team-visible geometry; discovery persistence and ownership concealment are enforced in the payload.)
- [x] 5.2 Report position periodically (gated by location consent from `live-location`) and surface newly revealed towers with a discovery cue when `HIDDEN` towers pop up. (Map runs the `POST /api/discovery/ping/` fallback loop — started immediately when tracking is off, or only after consent when tracking is on — and shows Bootstrap alert toasts + re-renders geometry on reveals.)
- [x] 5.3 Render a fog-of-war overlay for games using `FOG_REVEAL`, progressively clearing covered area. (Wireframe: a translucent veil over the map with team-visible zones punched out as holes; a fog zone's hole appears when it reveals. Sub-zone partial clearing by exact covered geometry was NOT implemented — see Implementation notes.)
- [x] 5.4 Tower detail: for `HIDDEN_UNTIL_ARRIVAL` conceal the challenge until inside the activation area; for `VISIBLE_ANYWHERE` show the challenge from afar but enable completion only inside the activation area. (`/state/` returns `challenge_visibility` + `challenge_hidden`; the app passes the live GPS fix and refetches on entering range; submit stays proximity-gated.)

## 6. Staff/creator config surfaces

- [x] 6.1 Expose per-tower `discoverability` and `challenge_visibility`, per-zone `fog_reveal_coverage_pct`, and the per-game/per-session defaults + `reveal_other_teams_ownership` in the staff API and editor UI. (Towers/Zones/Games editors + Session-detail overrides; plus a per-session Discovery matrix view at `/sessions/:id/discovery` with a staff Reveal button backed by `POST /api/staff/discovery/reveal/`.)

## 7. Tests

- [x] 7.1 Backward-compat: an all-default game returns every active tower with full ownership colouring — payload identical to pre-change (regression).
- [x] 7.2 `HIDDEN`: an undiscovered `HIDDEN` tower is absent from `GET /api/towers/`; after a proximity ping inside `proximity_meters` a `TowerDiscovery(method=PROXIMITY)` is created and the tower appears.
- [x] 7.3 `FOG_REVEAL` zone entry: a position inside the zone reveals its `FOG_REVEAL` towers (`method=ZONE_ENTRY`).
- [x] 7.4 `FOG_REVEAL` coverage: crossing `fog_reveal_coverage_pct` without entering reveals the towers (`method=ZONE_COVERAGE`); below threshold they stay hidden.
- [x] 7.5 Persistence: a discovered tower stays visible to the discovering team after another team conquers it and after it becomes ownerless.
- [x] 7.6 Challenge visibility: `HIDDEN_UNTIL_ARRIVAL` conceals the challenge from afar and reveals it inside the activation area; `VISIBLE_ANYWHERE` shows it from afar but blocks completion outside the area.
- [x] 7.7 `reveal_other_teams_ownership=False` hides other teams' control but keeps the caller's own; `True` shows all.
- [x] 7.8 Effective-value resolution: Session override beats Game default beats per-tower/per-zone null → Game default.
- [x] 7.9 Coverage ≥80% branch coverage on the visibility/discovery module; ruff-clean; single quotes.

## Implementation notes

Implemented 2026-07-21 on branch `impl/tower-visibility-and-discovery`
(worktree fork of the 12-change integration state, 525 tests baseline).

### Where things live
- `game/discovery.py` — NEW module: `evaluate_discovery`, `visible_towers`,
  `visible_zone_ids`, `staff_reveal`, coverage accumulation
  (`TeamZoneCoverage`), `_visible_now_q`. 91% branch coverage.
- `game/discovery_api.py` — NEW: `POST /api/discovery/ping/`,
  `GET /api/discovery/towers/`, `POST /api/staff/discovery/reveal/`.
- `game/models.py` — `Tower.discoverability` / `Tower.challenge_visibility`,
  `Zone.fog_reveal_coverage_pct`, module-level effective resolvers
  (`effective_discoverability` / `effective_challenge_visibility` /
  `effective_fog_reveal_pct`, mirroring `effective_proximity`) plus thin
  Tower/Zone methods; `TowerDiscovery` + `TeamZoneCoverage` models.
- `organize/models.py` — Game defaults + nullable Session overrides for the
  four knobs, added to `OVERRIDABLE_CONFIG_FIELDS`; `Session.visible_towers(team)`
  delegates to `game.discovery` (lazy import).
- Migrations: `game/0031_tower_visibility_discovery`,
  `organize/0021_tower_visibility_discovery`.

### Decisions & deviations from design.md
- **Task 1.5 (data migration)**: performed by the `AddField` defaults in
  `organize/0021` — Django writes `VISIBLE` / `VISIBLE_ANYWHERE` / `True` / `60`
  into every existing row at migrate time. A separate RunPython backfill would
  be a strict no-op, so none was added.
- **Effective resolvers** take `(session=None, game=None)` like
  `effective_conquest_rule`, not just `(game)`: the game-wide default itself
  has a Session override, so a Session context is preferred when available.
- **Coverage buffer**: each reported position is buffered by
  `COVERAGE_BUFFER_METERS = 50` (module constant in `game/discovery.py`) — a
  resolution/cost tradeoff, deliberately not a gameplay knob. Buffering and the
  covered/total area ratio are computed in EPSG:3857; the Mercator scale factor
  cancels in the ratio, but the absolute ground radius shrinks by ~cos(lat)
  (≈34 m at 46.5°N). Fine for the reveal mechanic; do not reuse for metric
  area reporting.
- **Zone-entry short-circuits coverage**: a position inside a fog zone reveals
  by ZONE_ENTRY and skips accumulation (coverage is only needed for teams that
  skirt a zone), and a revealed `TeamZoneCoverage` stops accumulating entirely.
- **Zone visibility (4.2)** is computed in Python per zone (zones are few);
  inactive member towers still count as "not fog" for zone visibility.
- **Submission serializer NOT touched**: no new check was inserted. Completion
  under both challenge-visibility values is already enforced by the existing
  GPS-proximity check (you cannot submit outside the activation area), and
  `HIDDEN_UNTIL_ARRIVAL` text-concealment is enforced in `TowerStateView`
  (which also 404s for towers the caller's team has not discovered).
- **`TowerSerializer.get_ownership`**: with a caller-team context it now
  resolves control in the caller's TeamGroup and honours
  `reveal_other_teams_ownership`; the legacy hardcoded group-1 lookup is kept
  verbatim for context-less callers (pre-existing TODO left in place).
- **Discovery from the map fetch**: `GET /api/towers/?lat=&lng=` also runs
  `evaluate_discovery` for team callers (spec: position params "drive
  discovery evaluation").
- **live-location integration**: `LocationPingView` runs the same
  `evaluate_discovery` after storing each ping and returns `newly_revealed`
  in its response.
- **Player map fallback loop** pings `/api/discovery/ping/` every 20 s whenever
  the session uses any non-VISIBLE tower — started immediately when tracking is
  off, or only after location consent when tracking is on. It may overlap with
  the live-location stream; the endpoint is idempotent (unique
  (session, team, tower)) so this is harmless, and the loop doubles as the
  toast source. `LocationStreamService` does not surface its own
  `newly_revealed` yet (map toasts come from the fallback loop).
- **Fog overlay is wireframe-grade**: world-covering translucent polygon with
  holes at team-visible zones; it does NOT render the exact covered geometry
  from `TeamZoneCoverage.visited` (that would need a coverage-geometry
  endpoint — left as a follow-up).
- **CurrentSession payload** gained a `visibility` object
  (`default_discoverability`, `uses_fog`, `uses_discovery`,
  `reveal_other_teams_ownership`) so the player app knows whether to run
  discovery/fog at all (`organize/api.py` CurrentSessionSerializer).
- The discovery matrix lists only towers whose EFFECTIVE discoverability is
  not VISIBLE (the interesting ones); staff bypass the player visibility
  filter everywhere (`is_staff` ⇒ omniscient).

### Expected merge conflict hotspots
- `organize/models.py` — `OVERRIDABLE_CONFIG_FIELDS` tuple + new Game/Session
  field blocks + new constants near the other choice constants.
- `game/models.py` — imports from organize, effective-helper block, Tower/Zone
  field additions, new models appended after `LocationConsent`.
- `game/admin_api.py` — AdminTower/AdminZone/AdminGame/AdminSession serializer
  field lists + new `discovery_matrix` action on `AdminSessionViewSet`.
- `geogame/urls.py` — imports + three new `api/discovery/...` paths.
- `game/serializers.py` (ZoneSerializer/TowerSerializer ownership methods),
  `game/views.py` (TeamVisibilityMixin + Zone/Tower viewsets),
  `game/api.py` (TowerStateView), `game/location_api.py` (ping response),
  `organize/api.py` (CurrentSessionSerializer).
- Migration numbering: `game/0031`, `organize/0021` — renumber at merge as
  usual.
- Frontend: `shared/game-api.service.ts` + `shared/staff-api.service.ts`
  interface additions; `staff/admin/games.component.ts`,
  `session-detail.component.ts`, `towers.component.ts`, `zones.component.ts`;
  `player/map/map.component.ts` was restructured (layer groups + fog +
  discovery loop) and will conflict with any parallel map change.

### Verification
- `manage.py test game organize --noinput`: 568 tests green (525 baseline +
  43 new) — re-run after every backend edit.
- `ruff check .` clean; `makemigrations --check` clean.
- `ng build player` / `ng build staff` (development) both build.
- Branch coverage on the new modules: `game/discovery.py` 91%,
  `game/discovery_api.py` 83% (≥80% gate).
