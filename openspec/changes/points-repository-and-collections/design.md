## Context

The shipped model is 2-tier: `organize.Game` is the reusable event configuration owning its `Zone`, `Tower`, `Challenge`, and `TeamGroup` data (via mandatory `game` FKs); `organize.Session` is one live run with a roster and clock. Ownership records hang off Team. This works when one Game == one map, but blocks the product goal of authoring many different games over the same physical points. The user's decision: make Towers and Zones a **repository** organised into **Collections**, and treat a Game as a **template** that references Collections. This change is the keystone the rest of the expansion builds on.

## Goals / Non-Goals

**Goals:**
- Towers and Zones are reusable library assets, not owned by a single Game.
- A `Collection` groups Towers + Zones and is the unit a Game references as its "map".
- A Game references one or more Collections; scoping still resolves cleanly to a set of Towers/Zones per Session.
- Separate the creator (authors the template) from the runner (runs a Session), with cloning to personalise a template.
- Zero data loss and unchanged runtime behaviour for existing Games after migration.

**Non-Goals:**
- `Tower.zone` single-FK → M2M migration (overlapping zones): handled by the separate `tower-zone-topology` change. This change keeps zone membership working as-is.
- Any new gameplay behaviour (visibility, locking, roles-as-mechanics) — those are separate changes.
- Fine-grained ACLs beyond creator/runner and "who may edit this Collection/Game".

## Decisions

- **`Collection` lives in the `game` app** next to the geometry it groups. `Collection`↔`Tower` and `Collection`↔`Zone` are many-to-many so a tower/zone can appear in several collections, and a collection can be composed/curated freely.
- **Remove `Tower.game` / `Zone.game`; resolve geometry through `Game.collections`.** Alternative considered: keep the `game` FK and add Collections alongside — rejected because two owners of truth for "which towers belong to this game" drift. Session/game scoping queries change from `Tower.objects.filter(game=...)` to `Tower.objects.filter(collections__games=...)`.
- **`Game.collections` is many-to-many.** A template can compose several collections (e.g. "old town" + "riverside"). Order is not significant for domination; trail mode adds its own ordering separately.
- **Cloning is a deep copy of template-owned data only** (rules config, challenge bank, TeamGroup taxonomy, role definitions, and the set of collection links), not of the geometry. The clone points at the **same** Collections/Towers/Zones — the repository is shared, only the template layer is duplicated. `Game.cloned_from` records provenance.
- **Creator vs runner as permissions, not a rename.** `Game.created_by` is the creator. A "runner" is whoever may create/control a Session under a Game. Model this with a lightweight authoring-permission (a `GameCollaborator` row with a role, or `is_staff` + ownership checks) rather than a full RBAC system.
- **Migration = one Collection per existing Game.** Named after the Game (e.g. "<Game name> map"), containing exactly that Game's current Towers + Zones, linked to that Game. Post-migration, every existing Session resolves the identical geometry it did before.

## Risks / Trade-offs

- [Scoping queries are scattered across serializers/viewsets and all assume `Tower.game` / `Zone.game`] → Introduce a single resolver (e.g. `Game.towers()` / `Session.towers()` helpers) and route every viewset through it; add tests that a Session sees exactly its Game's collections' geometry.
- [A Tower shared by two Games could be edited from one context and surprise the other] → Editing geometry is a repository-level action; the UI shows which Games/Collections use a Tower before editing. Ownership records remain per-Session so gameplay never leaks across Games.
- [Cloning could accidentally deep-copy geometry and defeat the repository] → Clone copies template rows only and re-links to the same Collections; covered by a test asserting the clone shares Tower/Zone rows by PK.
- [Removing `Tower.game` breaks admin/importer/tests that filter by it] → The data migration + a codemod pass; `data-import` and `admin-operations` deltas cover their share.

## Migration Plan

1. Add `Collection` + M2M through-tables and `Game.collections` (nullable/empty initially); add `Game.cloned_from` and authoring-permission model. Migrate schema.
2. Data migration: for each `Game`, create `Collection(name="<game> map")`, attach all `Tower`/`Zone` currently pointing at that Game, and link the Collection to the Game.
3. Switch all scoping code to resolve geometry via `Game.collections`.
4. Remove `Tower.game` / `Zone.game` fields in a follow-up migration once code no longer reads them.
5. Backfill `Game.created_by` from existing `created_by` where present.
