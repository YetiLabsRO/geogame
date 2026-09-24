# Design — content portability

## The identity problem

Two databases assign primary keys independently, so a bundle that says "challenge 37 belongs to tower 28" is meaningless on arrival. Three options were weighed:

1. **Name matching.** Towers named "Gara" in both installs are assumed to be the same tower. Rejected: names are not unique (there are two "Piata" towers in the legacy Alba Iulia data alone), and a rename silently forks the row.
2. **Export-local ids only**, every import creating fresh rows. Simple, and it makes updating a map you already shipped impossible — the second import duplicates the first.
3. **A `uuid` per exportable row**, minted at creation and preserved through export/import.

(3), chosen. It costs one migration per app and buys a well-defined answer to "is this the row I already have?" that survives renames, re-exports and round trips. `uuid4` rather than a content hash: a hash changes when the row is edited, which is precisely when identity must *not* change.

Within a bundle, every reference is by uuid. The bundle never contains a primary key.

## The manifest

`game/bundles.py` describes each exported model once:

```python
BundleSpec(
    key='towers',
    model=Tower,
    refs={'tower_type': 'tower_types'},   # FK  -> another spec, by uuid
    m2m={'zones': 'zones'},               # M2M -> list of uuids
    yielding_uniques=('rfid_code',),      # give it up on collision
    post_m2m_fields=('autocreate_zone',), # write after the m2m set lands
)
```

Export walks the manifest in dependency order; import walks it in the same order, resolving each reference against rows already imported in this pass or already present in the database. One ordering, one traversal, and a new model is an entry rather than a new function. The alternative — hand-written `export_tower()` / `import_tower()` pairs — was rejected after counting the models that would need them (fourteen today, and this project adds one every couple of weeks); hand-written pairs drift the moment someone adds a field and updates only the exporter.

Scalar fields are **derived** from the model, not listed: everything concrete and non-relational travels except the primary key, the uuid, auto timestamps, file fields and whatever the spec's `exclude` names. A project that adds config fields weekly would otherwise ship a bundle missing the newest knob, silently, and only notice when a game behaved differently on arrival. The price is that omissions must be declared — `created_by` (a user id that names nobody elsewhere), `created_at` (provenance of the source row, not of the content), `cloned_from` and `is_active` (local facts about a template), `ScoreMultiplier.session` (a run) — and that a relation the manifest neither carries nor excludes is a hard error rather than a surprise. A test asserts no spec exports a user reference or a source timestamp, so a spec added later inherits the rule.

## What travels and what does not

Travels: `TowerType`, `Zone`, `Tower`, `TowerPhoto` (+ the image file), `Collection`, `PresenceRequirement`, `Challenge` (+ `required_roles`), `Game` (rules), `GameRole`, `TeamGroup`, Game-owned `ScoreMultiplier`, `Trail` / `TrailStep` / `TrailEdge`.

Does not travel, each for a reason:

- **Sessions, Teams, Players, memberships, ownerships, submissions, scores, pings, locks, discoveries** — a run, not content. A bundle of a finished game should produce a game ready to run, not a ghost of someone else's run.
- **`NfcTag`** — a tag is a physical object with a provisioning secret, bound to the install that wrote it. Sending tag keys to another database is a security decision, not a convenience.
- **`GameCollaborator`, `created_by`** — user identities are local.
- **`Tower.rfid_code`** — physically bound to one town's hardware. Exported, because a bundle sent to the same organisation's second install *should* keep it, but treated as a conflict-prone unique: on collision the importer keeps the incumbent and reports it, rather than failing the whole import over a code someone will never scan.

## Import modes

- **`sync`** (default): match on uuid. Present → update the manifest's fields. Absent → create. This is "receive the newer version of a map I already have".
- **`copy`**: remint every uuid and suffix every unique slug, producing an independent second copy. This is "fork this map and make it mine". Never touches the rows already there.

Two modes rather than a flag per model, because the choice is really one question — *is this the same content or a copy of it?* — and asking it once per import is the honest place to ask it.

Sync **replaces** many-to-many membership rather than merging it: a Collection synced from upstream ends up holding exactly the towers the bundle names, so a tower added here and not there is dropped from that collection (the tower itself is untouched — membership is not the row). That is what "the bundle is the newer version of this" has to mean; anyone wanting to keep local additions should import as a copy.

Copy mode remints **everything**, including tower types and presence requirements. Sharing them across the two copies would be smaller but would couple them: editing a type in the copy would silently change the original's map. "Independent" is the contract, so it holds all the way down.

An import is atomic: one transaction, and any failure leaves the database as it was. A partially imported map is worse than no map, because it looks like a map.

## Preview before import

`inspect` parses and validates a bundle and reports what it holds and what would happen — how many rows of each kind, which already exist here, which slugs would collide — while writing nothing. The staff screen calls it before offering the import button. Importing a zip someone handed you without being told it will overwrite the map twelve people are standing on is not a defensible interaction.

## Reading untrusted zips

Import is staff-gated, but staff paste files from elsewhere. The reader therefore: refuses entries whose names escape the archive root (`..`, absolute paths), caps the uncompressed size and entry count, accepts media only under `media/` and only as image content, and validates `bundle.json` against the manifest before any write. A bundle whose `format_version` is unknown is refused with the version it saw — never partially applied on a guess.

## The legacy dump

The 2026 dump predates Sessions, Collections, TeamGroups, tower types and the M2M tower/zone topology. Its shape:

| Legacy | Now |
|---|---|
| `geogame_zone(name, color, scoring_type, shape)` | `Zone`, same four fields; overrides left NULL to inherit |
| `geogame_tower(..., zone_id NOT NULL)` | `Tower` + one `zones` M2M membership |
| `geogame_challenge(text, difficulty, tower_id NULL)` | `Challenge` with `game` set; NULL tower stays a game-wide challenge |
| `geogame_team(category smallint)` | a `TeamGroup` per distinct category |
| — | a `Collection` holding all of it, and a `Game` linking that Collection |

The scoring-type and category integers are unchanged between the schemas, so they map across as themselves; this was verified against the dump rather than assumed.

Reading it: `pg_restore` the custom-format dump into a scratch database, read with plain SQL, write through the ORM, drop the scratch database. Parsing the dump's `COPY` blocks directly was considered and rejected — it would mean re-implementing PostgreSQL's text encoding and WKB parsing to save one `createdb`. `--from-db` skips the restore for anyone who already has the old database on hand.

Names arrive with stray whitespace and newlines ("Trei măgari cu trei urechi\n"); they are stripped. Everything else is landed as it was found. The importer is loud rather than clever: it reports each thing it skipped and why.

## Two things the models made the importer do

**`Tower.save()` autocreates a zone.** When `autocreate_zone` is set and the tower belongs to no zone, saving conjures a circular Zone around it. During an import *every* tower belongs to no zone until its membership lands, so a straight save would mint a spurious circle per tower. `autocreate_zone` is therefore written after the m2m set, through the manifest's `post_m2m_fields` — declared rather than special-cased, so the next field with an authoring side effect has somewhere to go.

**A zone must keep a member tower.** Replacing a Collection's content means deleting its towers, and the at-least-one-tower guard refuses to delete a tower that is some zone's last member. Zones are therefore deleted first, which takes their membership rows with them and frees the towers. The KML importer had the same ordering and the same latent bug — it could not replace a collection it had already imported once — and is fixed with it.
