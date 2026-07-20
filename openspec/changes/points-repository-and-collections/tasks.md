## 1. Repository & Collection model

- [ ] 1.1 Add `game.Collection` (`name`, URL-safe `slug`, `description`, `created_by`, `created_at`) with M2M `towers` and `zones` (through-tables); admin + migrations.
- [ ] 1.2 Add `Game.collections` (M2M to `Collection`) and a `Game.towers()` / `Game.zones()` resolver (distinct union across linked collections).
- [ ] 1.3 Add `Session.towers()` / `Session.zones()` convenience resolvers delegating to `session.game`.

## 2. Data migration off the single-Game FK

- [ ] 2.1 Data migration: for every existing `Game`, create one `Collection` named "<game name> map", attach that Game's current `Tower`/`Zone` rows, and link the Collection to the Game.
- [ ] 2.2 Repoint all session/game scoping (viewsets, serializers, managers) from `Tower.game` / `Zone.game` to `Game.collections`-based resolvers; keep results identical for existing games (regression test).
- [ ] 2.3 Follow-up migration: remove `Tower.game` and `Zone.game` fields once no code reads them.

## 3. Creator vs runner roles & cloning

- [ ] 3.1 Set `Game.created_by` as the creator; add a lightweight authoring-permission (`GameCollaborator` with role `CREATOR`/`RUNNER`, or ownership + staff checks) governing who may edit a Game vs run Sessions under it.
- [ ] 3.2 Add `Game.cloned_from` self-FK and `POST /api/staff/games/{id}/clone/`: deep-copy rules config, challenge bank, TeamGroup taxonomy, role definitions, and collection links; re-link to the SAME collections (share geometry by PK).
- [ ] 3.3 Enforce: a runner may add challenges / adjust runnable config on their clone but not mutate the original template.

## 4. Repository & collection APIs

- [ ] 4.1 `GET/POST/PATCH/DELETE /api/staff/collections/` and membership add/remove of towers & zones.
- [ ] 4.2 Make `/api/staff/towers/` and `/api/staff/zones/` repository-scoped (filter by collection, not by game); a tower/zone may appear in several collections.
- [ ] 4.3 Show, when editing a Tower/Zone, which Collections and Games reference it (usage guard before edits/deletes).

## 5. Frontend (staff/creator)

- [ ] 5.1 Repository + Collection manager: browse the point library, create/curate collections, add/remove towers & zones.
- [ ] 5.2 Game (template) editor: attach collections; a "Clone game" action; creator-vs-runner affordances.

## 6. Tests

- [ ] 6.1 Migration test: post-migration each existing Session resolves the exact Towers/Zones it did before.
- [ ] 6.2 Sharing test: two Games linking the same Collection both see the same Tower rows (by PK); ownership records stay per-Session and never leak across Games.
- [ ] 6.3 Clone test: cloning copies template rows but shares Collection/Tower/Zone rows; original is not mutated by edits to the clone.
