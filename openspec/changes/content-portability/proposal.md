## Why

A map is the expensive part of this system. Walking a town, standing at each fountain and gate, deciding what counts as a point and writing a challenge for it — that is days of work, and right now it is trapped in whichever database it was typed into. There is no way to move a game to another install, no way to hand a finished map to another centre, and no way to get the existing Alba Iulia map — which exists, in a 2026 production dump of the pre-Session schema — back into the current software.

The KML importer is not that mechanism. It reads geometry from Google Earth and knows nothing about challenges, rules, roles, or types; it is how a map is born, not how one travels. `Game.clone` is not it either: it deep-copies a template *within* one database and deliberately shares geometry by primary key, which is exactly the wrong thing across two installs where primary keys mean nothing to each other.

What is missing is a **portable content bundle** — the map, the challenge bank and the rules in one file that another install can read — and a way to bring in what predates it.

## What Changes

- Add a **content bundle**: a single `.zip` holding `bundle.json` plus the referenced media. It carries repository geometry (Towers, Zones, their types and photos), Collections, the Game template (rules, challenge bank, roles, team groups, score multipliers, trail) and nothing that belongs to a run — no Sessions, Teams, Players, ownerships, submissions or scores.
- Give exportable rows a **stable identity** (`uuid`), so a bundle means the same thing in two databases. Importing the same bundle twice updates rather than duplicates; importing with `--mode copy` deliberately lands a second, independent copy.
- Add **`export_bundle` / `import_bundle` management commands**, and the same operations as staff endpoints, so moving content does not require shell access on both ends.
- Add a **staff screen** for it: pick games and collections, download; drop a zip, see what is in it *before* importing, choose sync or copy, import.
- Add an **`import_legacy_dump` command** that reads a pre-Session PostgreSQL dump (`geogame_zone` / `geogame_tower` / `geogame_challenge`) and lands its content in a named Collection and Game.

## Capabilities

### New Capabilities
- `content-bundles`: the bundle format and its guarantees; what is portable and what is deliberately not; how identity survives the trip; export selection, import modes, and the preview that precedes an import.

### Modified Capabilities
- `data-import`: alongside KML, the system imports a legacy pre-Session database dump into the repository.
- `staff-app`: the staff SPA scope gains export/import of content bundles.

## Impact

- **Models**: a `uuid` field on every model a bundle carries — `TowerType`, `Zone`, `Tower`, `TowerPhoto`, `Collection`, `PresenceRequirement`, `Challenge`, `ScoreMultiplier`, `Trail`, `TrailStep`, `TrailEdge`, `Game`, `GameRole`, `TeamGroup`. Two migrations (one per app), populated per row for existing data, unique and non-editable. No behavior reads it except the bundle layer.
- **New module** `game/bundles.py`: a declarative manifest (one entry per exported model: its fields, its references, how it is keyed) plus a generic exporter and importer over it. Adding a model to bundles later is an entry, not a new code path — which matters, because this project adds models constantly.
- **New endpoints**: `POST /api/staff/bundles/export/` (returns the zip), `POST /api/staff/bundles/inspect/` (what a zip contains, changing nothing), `POST /api/staff/bundles/import/`.
- **New commands**: `export_bundle`, `import_bundle`, `import_legacy_dump`.
- **Frontend**: a `/bundles` staff page.
- **Non-goal**: bundles are not a backup format and not a migration path between schema versions. A bundle records the schema version that wrote it and refuses a version it does not understand, rather than guessing.
- **A bundle is staff-only material.** It carries authored content including `Challenge.validation_code`, the code a venue's QR or NFC tag holds. That has to travel or the imported challenge cannot be completed, so a bundle file deserves the same handling as the staff app itself.
- **Known gap this surfaces**: `Game.clone` does not copy a Game's `Trail`. Bundles do. The clone gap is real but out of scope here; noted so it is not mistaken for a bundle bug.
