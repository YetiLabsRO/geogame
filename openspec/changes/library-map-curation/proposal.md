## Why

Collections are how a curator turns a pile of places into a map a game can use, and today they are curated through two `<select>` dropdowns of names and two lists of names. There is no map. You decide whether "Old Mill" belongs in "Riverside" with no way to see that it sits four kilometres from everything else in it, or that a zone in the collection contains none of its towers. The repository dropdown is unfiltered, so it degrades as the library grows — which is to say, exactly as the library succeeds.

Field mode has the mirror-image problem: its map draws the device position and whatever is being created right now, and nothing else. A curator can stand beside a tower they added last month and have no idea it is there. That does not merely inconvenience them; it produces duplicates.

Both are the same mistake. Spatial data is being judged through a non-spatial interface.

## What Changes

- Add a **map-first library** at `/library`: one map of the whole repository, towers painted by type, zones drawn as shapes. Choosing a collection highlights its members; tapping a tower or zone toggles its membership. The lists remain, as a searchable, filterable side panel rather than as the way things get added.
- **Search and filter the library** by name and by tower type, with the map and the panel showing the same filtered set, so a large repository stays navigable.
- **Show the selected collection on the field map.** Existing members render in place, distinct from what is being captured, so a curator sees what they already have while standing in it.
- **Open an existing element from the field map** to add media, attach a challenge, or fix its position — not only create new ones.
- **Replace drag-to-nudge with a crosshair.** Placement becomes a fixed crosshair at map centre that the map pans beneath, with a live readout of how far the chosen point has moved from the GPS fix and a way back to it. Marker drag stays for anyone who prefers it.
- Retire the old `/collections` page, redirecting it to the library so existing links keep working.

## Capabilities

### New Capabilities
- `library-map`: the map-first view of the repository; how collection membership is read and changed there; how search and filtering behave; and the guarantee that curating membership never destroys geometry.

### Modified Capabilities
- `field-authoring`: the field map shows the target collection's existing elements and can open them; tower placement is adjusted by a crosshair with a stated offset from the GPS fix.
- `staff-app`: the staff SPA scope gains the library map, and the collections page becomes an entry point to it.

## Impact

- **New endpoint** `GET /api/staff/library/`: every repository tower and zone with geometry, resolved styling, media counts and collection membership, in one response — so the map draws the whole library without a request per element.
- **No model changes and no migration.** Membership already lives on `Collection.towers` / `Collection.zones`, and the add/remove endpoints already exist and take id lists.
- **Frontend**: a new `/library` page; `/collections` redirects to it; field mode gains a collection overlay, an element inspector, and crosshair placement.
- **Depends on** `tower-types-and-styling` for the icons and colours that make a two-hundred-point map readable. Without it the page still works and every pin looks the same, which is the condition this change exists to fix.
- **Scale**: the library feed is one response for the whole repository. That is right for hundreds of elements and wrong for tens of thousands; the proposal states the assumption rather than pretending otherwise, and the endpoint is shaped so a bounding-box parameter can be added without changing its contract.
