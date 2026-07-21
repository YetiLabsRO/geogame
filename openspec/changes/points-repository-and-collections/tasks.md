## 1. Repository & Collection model

- [x] 1.1 Add `game.Collection` (`name`, URL-safe `slug`, `description`, `created_by`, `created_at`) with M2M `towers` and `zones` (through-tables); admin + migrations.
- [x] 1.2 Add `Game.collections` (M2M to `Collection`) and a `Game.towers()` / `Game.zones()` resolver (distinct union across linked collections).
- [x] 1.3 Add `Session.towers()` / `Session.zones()` convenience resolvers delegating to `session.game`.

## 2. Data migration off the single-Game FK

- [x] 2.1 Data migration: for every existing `Game`, create one `Collection` named "<game name> map", attach that Game's current `Tower`/`Zone` rows, and link the Collection to the Game.
- [x] 2.2 Repoint all session/game scoping (viewsets, serializers, managers) from `Tower.game` / `Zone.game` to `Game.collections`-based resolvers; keep results identical for existing games (regression test).
- [x] 2.3 Follow-up migration: remove `Tower.game` and `Zone.game` fields once no code reads them.

## 3. Creator vs runner roles & cloning

- [x] 3.1 Set `Game.created_by` as the creator; add a lightweight authoring-permission (`GameCollaborator` with role `CREATOR`/`RUNNER`, or ownership + staff checks) governing who may edit a Game vs run Sessions under it.
- [x] 3.2 Add `Game.cloned_from` self-FK and `POST /api/staff/games/{id}/clone/`: deep-copy rules config, challenge bank, TeamGroup taxonomy, role definitions, and collection links; re-link to the SAME collections (share geometry by PK).
- [x] 3.3 Enforce: a runner may add challenges / adjust runnable config on their clone but not mutate the original template.

## 4. Repository & collection APIs

- [x] 4.1 `GET/POST/PATCH/DELETE /api/staff/collections/` and membership add/remove of towers & zones.
- [x] 4.2 Make `/api/staff/towers/` and `/api/staff/zones/` repository-scoped (filter by collection, not by game); a tower/zone may appear in several collections.
- [x] 4.3 Show, when editing a Tower/Zone, which Collections and Games reference it (usage guard before edits/deletes).

## 5. Frontend (staff/creator)

- [x] 5.1 Repository + Collection manager: browse the point library, create/curate collections, add/remove towers & zones.
- [x] 5.2 Game (template) editor: attach collections; a "Clone game" action; creator-vs-runner affordances.

## 6. Tests

- [x] 6.1 Migration test: post-migration each existing Session resolves the exact Towers/Zones it did before.
- [x] 6.2 Sharing test: two Games linking the same Collection both see the same Tower rows (by PK); ownership records stay per-Session and never leak across Games.
- [x] 6.3 Clone test: cloning copies template rows but shares Collection/Tower/Zone rows; original is not mutated by edits to the clone.

## Implementation notes

All 17 tasks implemented. Suite: 237 tests green (208 baseline + 29 new), ruff clean,
`ng build staff` / `ng build player` clean.

**Migrations created** (numbering conflicts with parallel branches expected):
- `game/0022_collection.py` — Collection model + M2M through-tables.
- `organize/0011_game_collections_roles_cloning.py` — `Game.collections`,
  `Game.cloned_from`, `GameCollaborator`.
- `game/0023_backfill_collections.py` — data migration ('<game name> map' per Game;
  reverse is a no-op).
- `game/0024_remove_tower_zone_game_fk.py` — drops `Tower.game` / `Zone.game`.

**Design decisions / deviations the merger should know:**
- Scoping: new `GameGeometryScopedViewSetMixin` in `game/scoping.py` filters player
  Zone/Tower viewsets via `pk__in` over `Game.towers()`/`Game.zones()` (avoids M2M
  join row duplication under annotations). `GameScopedViewSetMixin` still serves
  Challenge/TeamGroup (their `game` FK remains).
- Staff `/api/staff/towers|zones/` are repository-wide with an optional
  `?collection=<id>` filter, and report usage as `collections`/`games`
  ([{id,name}] lists) replacing the removed `game` field. The `unassign_all`
  action stays scoped to the caller's current session's Game (safety: a sweep must
  not close ownerships of other games sharing the repository).
- Rules config (proximity/cooloff) now always resolves via `team.session.game`
  (in `TeamTowerChallengeSerializer.validate`, `TowerStateView`,
  `Tower.team_in_cooloff`) since towers no longer know a single Game.
- `Tower.unassign()` zone-control recomputation iterates
  `TeamGroup.objects.filter(game__collections__zones=zone).distinct()` — covers
  every Game sharing the zone.
- Permissions: `Game.can_edit(user)` = superuser, creator, or CREATOR collaborator;
  **games with `created_by=None` (legacy) stay editable by any staff** to preserve
  baseline behavior. Enforced on AdminGameViewSet update/destroy and on
  AdminChallengeViewSet create/update/destroy (challenge bank = template data).
  Session control (create/pause/resume, `pause_all`) intentionally stays open to
  all staff (= runners).
- Clone: `POST /api/staff/games/{id}/clone/` accepts optional `{name, slug}`;
  auto-slug `<source-slug>-clone(-N)`; clone starts `is_active=False`; copies all
  rules/Phase-10 knobs, Challenge rows (pointing at the SAME towers), TeamGroup
  rows; `collections.set(source.collections)`. "Role definitions" from the task
  text: no roles model exists yet (future change) — nothing to copy.
- `import_data` gained `--collection <name>` (default 'Imported map'); idempotent
  by replacement per collection (deletes that collection's Tower/Zone rows, not
  the whole tables; tower-bound challenges go via FK cascade). It no longer wipes
  ALL challenges globally.
- Test helpers `_make_zone`/`_make_tower` in `game/tests.py` now attach geometry to
  a per-game default collection (`_game_collection`). The migration parity test
  (`CollectionBackfillMigrationTest`) is a `TransactionTestCase` using
  `MigrationExecutor` — it migrates back to `game.0022`, seeds legacy FK rows,
  migrates forward, and restores head in tearDown; it runs last and adds ~15s.

**Expected merge conflict hotspots:** `game/models.py`, `organize/models.py`,
`game/admin_api.py`, `geogame/urls.py`, `game/admin.py`, `game/tests.py`
(helpers + imports), `frontend/projects/shared/src/lib/staff-api.service.ts`,
`frontend/projects/staff/src/app/app.routes.ts` + `app.html`,
`games.component.ts`. Migration renumbering: `game/0022-0024`, `organize/0011`.
