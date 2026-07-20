## Why

Today `Tower` and `Zone` carry a mandatory `game` foreign key, so geometry is owned by exactly one Game and cannot be reused. The product direction is a **reusable repository of points** that a creator draws from when authoring many different games on the same physical map — "multiple games on the same set of towers." This change decouples geometry from any single Game, introduces `Collection`s (named, reusable groupings of towers and zones — the "maps"), and separates the **creator** who authors a Game template from the **runner** who runs a Session, including cloning a template to personalise it.

## What Changes

- Introduce a `game.Collection` model: a named, reusable grouping of Towers and Zones (many-to-many both ways). A Collection is the reusable "map/territory" that Games point at.
- Decouple `Tower`/`Zone` from single-Game ownership: they become **repository (library) assets** grouped by `Collection` rather than owned by one Game. Their `game` FK is removed in favour of Collection membership.
- A `Game` (the creator-authored **template**) references one or more Collections; scoping resolves `Session → Game → Collections → Towers/Zones`.
- Add **creator vs runner** roles: the creator authors a Game (collections, rules, challenge bank, roles); the runner launches and controls a Session. A runner can **clone** a Game (deep copy of rules, challenge bank, and collection links) to personalise it and run the clone.
- Migration: for each existing Game, create one Collection holding that Game's current Towers + Zones and link the Game to it, preserving all data and existing scoping behaviour.
- Staff/creator API + admin for managing the repository, collections, and cloning.

## Capabilities

### New Capabilities
- `collections`: a reusable repository of Towers and Zones grouped into named Collections that Games reference.
- `game-authoring-roles`: creator vs runner separation, per-object authoring permissions, and Game (template) cloning.

### Modified Capabilities
- `geographic-map`: Towers and Zones belong to the repository (Collections), not to a single Game.
- `game-configuration`: a Game references Collections for its map instead of owning geometry directly.
- `data-import`: KML import seeds the repository and a Collection rather than a Game's geometry.

## Impact

- **Models**: new `game.Collection` + through-tables (`Collection`↔`Tower`, `Collection`↔`Zone`); remove `Tower.game` / `Zone.game`; add `Game.collections` (M2M); add `Game.created_by` as the creator and a `Game.cloned_from` self-FK; authoring-permission model or role flags.
- **APIs**: new `/api/staff/collections/`, `/api/staff/towers/` and `/api/staff/zones/` become collection-scoped (not game-scoped); `POST /api/staff/games/{id}/clone/`.
- **Scoping**: session-scoped and game-scoped viewsets resolve geometry through `Game.collections` instead of `Tower.game` / `Zone.game`.
- **Migrations**: data migration creating one Collection per existing Game; **cross-cutting** across the `game` and `organize` apps and the KML importer.
- **Frontend**: staff/creator UI gains a repository + collection manager and a "clone game" action.
