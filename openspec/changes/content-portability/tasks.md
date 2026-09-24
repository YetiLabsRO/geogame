# Tasks — content portability

## 1. Stable identity

- [x] 1.1 Add `uuid = UUIDField(default=uuid4, unique=True, editable=False)` to every model a bundle carries: `TowerType`, `Zone`, `Tower`, `TowerPhoto`, `Collection`, `PresenceRequirement`, `Challenge`, `ScoreMultiplier`, `Trail`, `TrailStep`, `TrailEdge` (game) and `Game`, `GameRole`, `TeamGroup` (organize). The child models need it as much as the parents: the manifest resolves every reference by uuid, so a model without one cannot be referenced.
- [x] 1.2 Migrations `game.0042_content_bundle_uuids` / `organize.0027_content_bundle_uuids`: add the column nullable **and with no default**, backfill each existing row with its own uuid, then tighten to unique. Confirmed the hard way: `AddField` with a callable default evaluates it once and writes that one value into every existing row, and the unique index then refuses to build.
- [x] 1.3 Tests: two rows never share a uuid; a uuid survives `save()` after a rename; existing rows all got one.

## 2. The manifest and the bundle format

- [x] 2.1 `game/bundles.py`: `BundleSpec` (key, model, fields, geometry fields, FK refs, M2M refs, file fields, parent ref) and `MANIFEST` in dependency order.
- [x] 2.2 `export_bundle(games, collections)` → an in-memory zip: `bundle.json` + `media/`. Geometry as GeoJSON; `DurationField` as ISO-8601; datetimes as ISO-8601 UTC.
- [x] 2.3 Selection closure: a Game pulls its Collections, which pull their Towers and Zones, which pull types, photos and presence requirements; a Collection alone pulls geometry without challenges. Challenges come from the Games in the selection, never from the towers.
- [x] 2.4 `format_version` constant, written on export and checked on import.
- [x] 2.5 Tests: a bundle round-trips through export → import → export byte-identical in content (not in export timestamp); geometry survives to the same coordinates; every reference in `bundle.json` is a uuid and never a pk.

## 3. Reading bundles safely

- [x] 3.1 `read_bundle(fileobj)`: zip entry-name validation (no absolute paths, no `..`), entry-count and uncompressed-size caps, media confined to `media/`, `bundle.json` schema-validated against the manifest before any write.
- [x] 3.2 Unknown `format_version` → refuse, naming the version found.
- [x] 3.3 Tests: a path-traversal entry, an oversized entry, a bundle with a missing referenced uuid, a bundle with a future version — each refused, each writing nothing.

## 4. Importing

- [x] 4.1 `import_bundle(bundle, mode)` in one transaction, walking the manifest in order and resolving refs through a uuid → instance map.
- [x] 4.2 `sync` mode: match on uuid, update the manifest's fields, create what is absent.
- [x] 4.3 `copy` mode: remint uuids, suffix colliding slugs (`alba-iulia-2`), never touch an existing row.
- [x] 4.4 Unique-value conflicts (`Tower.rfid_code`, `NfcTag`-free by construction): keep the incumbent, import the rest, record the conflict in the report.
- [x] 4.8 `post_m2m_fields`: `Tower.autocreate_zone` is written only after the tower's `zones` set lands, or `Tower.save()` mints a circular zone for every arriving tower. A model invariant refusing the bundle's shape (the at-least-one-tower guard) is re-raised as a BundleError naming it.
- [x] 4.5 Media: write image files into storage under fresh names; never trust a path from the archive.
- [x] 4.6 `ImportReport`: created / updated / skipped counts per kind, plus a list of conflicts. Returned by the command, the endpoint and the UI.
- [x] 4.7 Tests: import into an empty database; re-import updates in place; `copy` duplicates and leaves the original alone; a failure mid-import rolls back everything; an rfid collision imports the tower and reports.

## 5. Inspecting

- [x] 5.1 `inspect_bundle(bundle)`: counts per kind, which uuids already exist here, which slugs would collide — reusing the same validation path as import so a bundle that inspects cleanly imports cleanly.
- [x] 5.2 Tests: inspection of a bundle that would collide reports the collisions and writes nothing (asserted by row counts and by storage contents).

## 6. Commands

- [x] 6.1 `manage.py export_bundle --game <slug|id>… --collection <slug|id>… -o out.zip`, `-o -` for piping (a `--stdout` flag would shadow `call_command(stdout=...)`).
- [x] 6.2 `manage.py import_bundle <file> [--mode sync|copy] [--dry-run]`, printing the report; `--dry-run` runs the inspect path.
- [x] 6.3 Tests: both commands end to end over a temporary file.

## 7. Endpoints

- [x] 7.1 `POST /api/staff/bundles/export/` — body names games and collections, returns the zip as an attachment. POST rather than GET: the selection is a list, and a URL is not where a fifty-item selection belongs.
- [x] 7.2 `POST /api/staff/bundles/inspect/` — multipart upload, returns the inspection, changes nothing.
- [x] 7.3 `POST /api/staff/bundles/import/` — multipart upload plus mode, returns the report.
- [x] 7.4 `IsAdminUser` on all three; upload size limit; tests for a player and for an anonymous caller on each.

## 8. Staff screen

- [x] 8.1 `/bundles` route behind `staffGuard`, in the sidebar's authoring section.
- [x] 8.2 Export panel: games and collections with checkboxes, a running count of what the selection will carry, download.
- [x] 8.3 Import panel: file picker → inspection shown as a table (kind, in bundle, already here, colliding) → mode choice → import → report. The import button stays disabled until an inspection has come back.
- [x] 8.4 Tests: the component renders an inspection and does not offer import before one.

## 9. Legacy dump import

- [x] 9.1 `manage.py import_legacy_dump <dump> --collection <name> --game <name>`, with `--from-db <name>` to read an already-restored database and `--keep-scratch-db` for debugging.
- [x] 9.2 Restore into a scratch database with `pg_restore`, read the legacy tables with plain SQL, drop the scratch database afterwards. Verify the expected legacy tables exist before writing anything.
- [x] 9.3 Map zones, towers (legacy single `zone_id` → one M2M membership), and challenges (NULL tower → game-wide). Strip stray whitespace from names.
- [x] 9.4 Create the Collection and the Game, link them, derive the Game's `base_point` from the imported towers so the staff map opens on the town rather than on null island.
- [x] 9.5 One TeamGroup per distinct legacy team category; no teams, rosters or scores.
- [x] 9.6 `--replace` to re-run over an existing collection; refuse without it. Delete zones **before** towers — the at-least-one-tower guard refuses a tower that is a zone's last member, so towers-first cannot replace anything. `import_data` (KML) had the same latent bug and is fixed with it.
- [x] 9.7 Tests over a fixture that exercises the mapping without needing a real dump: NULL-tower challenges, a duplicate rfid code, a name with a trailing newline.

## 10. Run it

- [x] 10.1 Import `cercetador.20260924.dump` locally into collection and game "Alba Iulia": 30 zones, 48 towers, 122 challenges (66 tower-bound, 56 game-wide), 3 TeamGroups, base point over the town.
- [x] 10.2 Export the result as a bundle and re-import it in `copy` mode as a live check that the two halves of this change agree — also kept as a test (`LegacyDumpImportTest.test_imported_content_can_then_be_exported_as_a_bundle`).
- [x] 10.3 `ruff check .` clean; `ng build staff` clean; backend suite with coverage.

## Not done here

- `Game.clone` still does not copy a Game's `Trail`, so cloning a trail-mode template produces a game with no trail. Bundles carry it. Out of scope for this change, and noted so it is not read as a bundle bug.
- The staff sidebar test (`app.nav.spec.ts`) fails on the in-flight `/library` route, which has no nav entry. Unrelated to this change and left alone.
