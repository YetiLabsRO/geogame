## Why

Field mode fills a library, and a library is only as useful as it is *queryable*. Today a Tower carries a name, a point, and nothing that says what kind of thing it is. Assembling a game at home therefore means reading a list of names and remembering which of them were fountains — and in the field it means typing a full configuration for every tower, outdoors, one-handed.

`Tower.category` looks like it should carry this and does not: it is `NORMAL` / `RFID`, the *capture method*, and overloading it would break RFID capture.

There is also no visual vocabulary. Every tower renders as the same circle in the map editor, the live overview and the replay. On a library map of two hundred points that is unreadable, which is a problem the next change runs directly into.

## What Changes

- Add **`TowerType`** — a small managed lookup a curator edits once: name, icon, colour, and an optional default capture radius. "Fountain, droplet icon, blue, 25 m."
- Give **`Tower` a nullable type plus per-tower `icon` and `colour` overrides**, so a type supplies the defaults and any individual tower can disagree without leaving the type.
- **Resolve the capture radius through the type**: tower override → type default → Game default. This threads through all three places the radius is currently derived, including the SQL `Coalesce` behind nearby-tower filtering.
- **Serve resolved styling from the API** (`icon`, `color` as computed read-only fields), so no client re-implements the fallback chain and drifts from the others.
- Give the staff app a **tower-type manager**, and give field mode a **one-tap type chip row** so dropping a styled, pre-configured tower is a single action rather than a form.
- Paint towers by type wherever they are drawn: map editor, field mode, and the library map that the `library-map-curation` change adds.

## Capabilities

### New Capabilities
- `tower-types`: the type lookup and what it carries; the tower-over-type-over-game resolution order for styling and capture radius; the requirement that resolved values are served rather than recomputed per client.

### Modified Capabilities
- `field-authoring`: field capture gains type selection as a first-class one-tap action, and the capture panel shows what the chosen type implies.
- `staff-app`: the staff SPA scope gains tower-type management.

## Impact

- **Models**: new `game.TowerType` (name, slug, icon, colour, nullable `proximity_meters`, description, ordering). `Tower` gains nullable `tower_type` FK and nullable `icon` / `color` overrides. One migration, entirely additive — every existing tower resolves to the current defaults with a null type.
- **Resolution hazard, handled explicitly**: `effective_proximity()` in `game/models.py`, the `Coalesce` in `game/views.py`'s nearby filter, and `game/presence.py`'s geofence fallback must agree. The Python helper gains the type layer and the SQL annotation coalesces through the joined type; a test asserts the two agree for the same tower, because a disagreement here shows up as "the tower is in my list but will not capture".
- **APIs**: `/api/staff/tower-types/` CRUD; `AdminTowerSerializer` gains `tower_type`, writable `icon`/`color` overrides, and read-only resolved `icon`/`color`.
- **Frontend**: a `/tower-types` manager page with a nav entry; a type chip row in field mode; type-driven marker paint in the map editor and field map.
- **No gameplay change by default.** A tower with no type behaves exactly as today. Nothing here alters scoring, visibility, or capture rules beyond the radius fallback gaining one step that is only consulted when the tower itself is silent.
- **Deliberate boundary**: the type carries styling and capture radius only. `discoverability`, `challenge_visibility` and `initial_bonus` stay per-tower. Every default a type carries is another resolution chain to keep consistent across the Python and SQL paths, and the radius is the one that earns it.
