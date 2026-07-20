## Context

The `points-repository-and-collections` foundation makes Towers and Zones reusable repository assets grouped into `Collection`s that Games reference. That gives curators a library to build up — but building it still assumes a desk: type coordinates or click a web map. Real game design for a scouting geogame happens **on foot**. A curator walks the old town, sees a fountain worth a tower, photographs it so players know what to look for, and wants to record "a tower, here, with this photo, in the riverside collection" without going home first. This change layers an on-site mobile authoring flow on top of the repository APIs. It is a mode of the staff SPA (`frontend/projects/staff`), which is web+mobile; the desk web authoring path is unchanged.

## Goals / Non-Goals

**Goals:**
- Let a curator create a Tower at their current device GPS position in one action, with visible accuracy and provenance.
- Let a curator attach reference photos to a Tower from the device camera.
- Let a curator draw a new Zone or adjust an existing one on the mobile map, including by walking the boundary.
- Let a curator attach challenges to a Tower while on site.
- File every field-created/adjusted Tower and Zone into a target Collection, with a draft/publish path.
- Tolerate poor field connectivity: capture offline, sync on reconnect.

**Non-Goals:**
- The repository/Collection model itself — owned by `points-repository-and-collections`; this change only *uses* it.
- Native app packaging or native NFC — web geolocation + `getUserMedia` camera in the mobile browser are sufficient; native NFC is the `nfc-native-and-secure-links` change.
- Live location tracking of the curator or players — that is `live-location-tracking`. Field authoring only reads a one-shot fix per capture.
- Challenge *type* semantics (photo/NFC/etc.) — owned by `challenge-type-system`; here we only associate a Challenge with a Tower.
- Redesigning desk-based web authoring.

## Decisions

- **Field authoring is a mobile mode of the staff SPA, not a new app.** It reuses staff auth (`is_staff`) and the `game-authoring-roles` authoring permission, and writes through the same repository APIs (`/api/staff/towers/`, `/api/staff/zones/`, Collection membership actions). Alternative considered: a separate curator app — rejected because it would duplicate auth, map, and repository plumbing for one flow.
- **Reference photos are a new `game.TowerPhoto` model, not a single `Tower.image` field.** Curators photograph an objective from several angles; a Tower MAY have many reference photos. Alternative considered: one `ImageField` on Tower — rejected as too limiting for on-site scouting. `TowerPhoto` records `captured_by`/`captured_at` for provenance and is explicitly distinct from the player submission photos on `TeamTowerChallenge`.
- **"Drop at current GPS" reads a one-shot geolocation fix and stores the accuracy** in `Tower.authored_accuracy_m` as provenance, and warns/offers averaging when accuracy is poor. Alternative considered: silently trust the first fix — rejected because urban GPS error routinely exceeds tower `proximity_meters`, which would make the objective uncapturable.
- **Zones can be drawn by walking the boundary**: each "mark" appends a vertex at the current fix; the curator closes the polygon to save. This reuses the same one-shot geolocation as tower drops and is the natural on-site gesture. Tap/drag vertex editing is also supported for correction and for adjusting existing zones.
- **Field-created geometry is filed into a target Collection immediately**, selected when entering the mode and switchable per element, so the curator never has to reconcile "loose" towers later. Draft staging reuses the existing `Tower.is_active` flag (create inactive, activate when ready) rather than adding a new status field — keeping the model change minimal and backward compatible.
- **Offline capture is client-side (IndexedDB queue) with sync-on-reconnect.** The server APIs stay ordinary REST; the mode queues creates/uploads while offline and replays them when the network returns, surfacing per-item failures. Alternative considered: a server-side draft/sync protocol — rejected as over-engineering for a single-author, mostly-additive flow.

## Risks / Trade-offs

- [Urban GPS accuracy is often worse than a tower's `proximity_meters`, so a dropped tower may be physically uncapturable] → show accuracy live, warn past a threshold, and offer multi-reading averaging and manual nudge before save; store `authored_accuracy_m` so poor captures are auditable.
- [Offline queue could lose data if the browser storage is cleared or the device dies] → persist to IndexedDB (survives reload), show a pending-sync count, and never clear a queued item until the server confirms it; surface failures for explicit retry.
- [Photo uploads over field cellular can be large and flaky] → downscale/compress reference photos client-side before queueing, and upload them as part of the sync step with retry.
- [A curator could author into a Collection they are not permitted to edit] → gate the target-Collection selector and every write to staff authorised for that Collection (see the `game-authoring-roles` capability); covered by a permission test.
- [Field-created draft towers leaking into live sessions before they are ready] → default field drafts to `is_active=False`; live session scoping already excludes inactive towers (see the `geographic-map` capability); covered by a draft-exclusion test.

## Migration Plan

1. Add `game.TowerPhoto` and nullable `Tower.authored_accuracy_m`; one schema migration. No data backfill needed (both are additive; existing towers keep `authored_accuracy_m = NULL` and zero photos).
2. Ensure media storage is configured for reference photos (same storage backend as existing submission photos).
3. No changes to existing rows and no behaviour change for desk-based authoring; the field mode is purely additive and opt-in.
