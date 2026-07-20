## 1. Models & migrations

- [ ] 1.1 Add `game.TowerPhoto` (`tower` FK, `image` ImageField, optional `caption`, `captured_by`, `captured_at`) with admin registration.
- [ ] 1.2 Add nullable `Tower.authored_accuracy_m` (float) to record the GPS accuracy of a field-dropped tower as capture provenance.
- [ ] 1.3 One schema migration for `TowerPhoto` + `Tower.authored_accuracy_m`; confirm media storage is configured for reference photos.

## 2. Field authoring APIs

- [ ] 2.1 Extend `POST /api/staff/towers/` to accept a capture-accuracy value and a target-Collection id, creating the tower and adding it to that Collection in one call; allow creating it inactive (draft).
- [ ] 2.2 Add reference-photo endpoints: `POST /api/staff/towers/{id}/photos/` (multipart upload), `GET` list, `DELETE /api/staff/towers/{id}/photos/{photo_id}/`.
- [ ] 2.3 Extend `POST/PATCH /api/staff/zones/` to accept walked/tapped polygon vertices and a target-Collection id, filing new zones into that Collection; support adjusting an existing zone's boundary.
- [ ] 2.4 Add a field action to attach a Challenge (new or existing) to a Tower and persist the association.
- [ ] 2.5 Gate all field-authoring writes to staff authorised to edit the target Collection (see the `game-authoring-roles` capability).

## 3. Staff SPA — field authoring mode (mobile)

- [ ] 3.1 Add a field authoring mode entry point; request location permission; render a Leaflet map centered on the device's current GPS fix; select a target Collection.
- [ ] 3.2 "Drop tower here" control that reads a one-shot geolocation fix, shows accuracy in metres live, and allows nudge / re-read / multi-reading average before save.
- [ ] 3.3 Camera capture (`getUserMedia`/file input) to attach one or more reference photos to a tower, downscaled/compressed client-side.
- [ ] 3.4 Zone drawing: walk-the-boundary (append a vertex at the current GPS mark), plus tap/drag vertex editing and adjusting an existing zone.
- [ ] 3.5 Attach-challenge bottom sheet to create/select a Challenge for the current tower.
- [ ] 3.6 One-handed, large-touch, outdoor-readable UI (standalone components, signals, `@if`/`@for`, `OnPush`); target-Collection switcher and inactive-draft toggle.

## 4. Offline capture & sync

- [ ] 4.1 IndexedDB queue for field edits (towers, photos, zones, challenge links) captured while offline.
- [ ] 4.2 Pending-sync indicator with a queued-item count; sync queued edits on reconnect and surface per-item failures for retry.

## 5. Tests

- [ ] 5.1 API test: dropping a tower at a GPS point creates the `Tower` with the given accuracy and adds it to the target Collection.
- [ ] 5.2 API test: uploading a reference photo creates a `TowerPhoto` linked to the tower with `captured_by`/`captured_at`.
- [ ] 5.3 API test: creating and adjusting a zone persists the `PolygonField` and files the new zone into the target Collection.
- [ ] 5.4 API test: attaching a challenge associates it with the tower and is visible to players at that tower.
- [ ] 5.5 Permission test: a staff user not authorised for the target Collection cannot create/adjust geometry in it.
- [ ] 5.6 Draft test: a field-created inactive tower is excluded from live session scoping until it is activated.
- [ ] 5.7 Frontend test: offline-queued field edits persist across reload and sync on reconnect, with failures surfaced for retry.
