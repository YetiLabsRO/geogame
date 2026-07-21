## 1. Models & migrations

- [x] 1.1 Add `game.TowerPhoto` (`tower` FK, `image` ImageField, optional `caption`, `captured_by`, `captured_at`) with admin registration.
- [x] 1.2 Add nullable `Tower.authored_accuracy_m` (float) to record the GPS accuracy of a field-dropped tower as capture provenance.
- [x] 1.3 One schema migration for `TowerPhoto` + `Tower.authored_accuracy_m`; confirm media storage is configured for reference photos.

## 2. Field authoring APIs

- [x] 2.1 Extend `POST /api/staff/towers/` to accept a capture-accuracy value and a target-Collection id, creating the tower and adding it to that Collection in one call; allow creating it inactive (draft).
- [x] 2.2 Add reference-photo endpoints: `POST /api/staff/towers/{id}/photos/` (multipart upload), `GET` list, `DELETE /api/staff/towers/{id}/photos/{photo_id}/`.
- [x] 2.3 Extend `POST/PATCH /api/staff/zones/` to accept walked/tapped polygon vertices and a target-Collection id, filing new zones into that Collection; support adjusting an existing zone's boundary.
- [x] 2.4 Add a field action to attach a Challenge (new or existing) to a Tower and persist the association.
- [x] 2.5 Gate all field-authoring writes to staff authorised to edit the target Collection (see the `game-authoring-roles` capability).

## 3. Staff SPA — field authoring mode (mobile)

- [x] 3.1 Add a field authoring mode entry point; request location permission; render a Leaflet map centered on the device's current GPS fix; select a target Collection.
- [x] 3.2 "Drop tower here" control that reads a one-shot geolocation fix, shows accuracy in metres live, and allows nudge / re-read / multi-reading average before save.
- [x] 3.3 Camera capture (`getUserMedia`/file input) to attach one or more reference photos to a tower, downscaled/compressed client-side.
- [x] 3.4 Zone drawing: walk-the-boundary (append a vertex at the current GPS mark), plus tap/drag vertex editing and adjusting an existing zone.
- [x] 3.5 Attach-challenge bottom sheet to create/select a Challenge for the current tower.
- [x] 3.6 One-handed, large-touch, outdoor-readable UI (standalone components, signals, `@if`/`@for`, `OnPush`); target-Collection switcher and inactive-draft toggle.

## 4. Offline capture & sync

- [x] 4.1 IndexedDB queue for field edits (towers, photos, zones, challenge links) captured while offline.
- [x] 4.2 Pending-sync indicator with a queued-item count; sync queued edits on reconnect and surface per-item failures for retry.

## 5. Tests

- [x] 5.1 API test: dropping a tower at a GPS point creates the `Tower` with the given accuracy and adds it to the target Collection.
- [x] 5.2 API test: uploading a reference photo creates a `TowerPhoto` linked to the tower with `captured_by`/`captured_at`.
- [x] 5.3 API test: creating and adjusting a zone persists the `PolygonField` and files the new zone into the target Collection.
- [x] 5.4 API test: attaching a challenge associates it with the tower and is visible to players at that tower.
- [x] 5.5 Permission test: a staff user not authorised for the target Collection cannot create/adjust geometry in it.
- [x] 5.6 Draft test: a field-created inactive tower is excluded from live session scoping until it is activated.
- [x] 5.7 Frontend test: offline-queued field edits persist across reload and sync on reconnect, with failures surfaced for retry.

## Implementation notes

- **Backend surface** (`game/models.py`, `game/admin_api.py`, `game/admin.py`,
  migration `game/migrations/0026_field_authoring.py`):
  - `Tower.authored_accuracy_m` (nullable float) + `game.TowerPhoto`
    (`tower` FK related_name `photos`, `image` → `tower_photos/` on the same
    media storage as submission photos, `caption`, `captured_by`, `captured_at`),
    registered in Django admin (standalone + inline on Tower).
  - `AdminTowerSerializer`: write-only `lat`/`lng` (create requires both),
    `authored_accuracy_m`, write-only `collection` (files the new tower — and,
    idempotently, its linked zone — into that Collection at create; ignored on
    update), read-only GeoJSON `location` + nested `photos`.
  - `AdminZoneSerializer`: write-only `vertices` ([[lng, lat], …], ring closed
    server-side, ≥3 required) on create AND update (boundary adjust), write-only
    `collection` (create-time filing only), read-only GeoJSON `shape`.
  - `POST/GET /api/staff/towers/{id}/photos/`,
    `DELETE /api/staff/towers/{id}/photos/{photo_id}/` — upload accepts
    multipart or base64 data URL (reuses `Base64ImageField`, so the offline
    queue can replay JSON).
  - `POST /api/staff/towers/{id}/attach-challenge/` — `{challenge}` re-points
    an existing challenge, or `{game, text, difficulty}` creates one; both
    gated by `Game.can_edit` (the challenge bank is template data).
  - Task 2.5 gate: new `Collection.can_author(user)` (superuser → yes; the
    collection's `created_by` → yes; otherwise `Game.can_edit` on ALL
    referencing games; unreferenced collections without a creator stay open to
    staff — mirrors the legacy `Game.can_edit` behaviour). Enforced via
    `CollectionAuthorGateMixin` on the staff tower/zone viewsets for
    create-into-collection, update, and destroy.
- **Frontend surface**:
  - `frontend/projects/shared/src/lib/staff-api.service.ts`: `AdminTower` grew
    `location`/`authored_accuracy_m`/`photos`; `AdminZone` grew `shape`; new
    `createTower`/`createZone`/`updateZone(vertices)`/photo/attach-challenge
    methods and payload types.
  - `frontend/projects/shared/src/lib/field-sync.service.ts`: offline queue
    (signals: `items`, `pendingCount`, `failedCount`, `online`, `syncing`),
    FIFO replay through the ordinary REST endpoints, local-id → server-id
    remap so photos/challenges queued against a not-yet-synced tower follow it
    once the create is confirmed, sync-on-reconnect via the `online` event,
    per-item failure state with retry/discard. Spec (task 5.7):
    `field-sync.service.spec.ts`, runs under `ng test shared` (vitest).
  - `frontend/projects/staff/src/app/field/field-mode.component.ts` (route
    `/field`, staff-guarded, nav link "Field mode"): Leaflet map centered on
    the device fix with a live ±accuracy chip (warn > 15 m), drop-tower with
    re-read / multi-reading averaging / drag-to-nudge, camera capture via
    `<input type=file capture=environment>` downscaled to ≤1280 px JPEG,
    walk-the-boundary + tap-to-add vertex zone drawing and adjust-existing,
    attach-challenge bottom sheet (existing or new), collection switcher +
    draft toggle (drafts save `is_active=false`), pending-sync panel with
    counts, per-item errors, retry/discard. Big-button (btn-lg) wireframe UI.
- **Deviations**:
  - Task 4.1 says "IndexedDB queue"; implemented as a `localStorage`-persisted
    queue instead. Same contract (survives reload, nothing dropped until the
    server confirms, failures kept for retry) with far less machinery;
    client-side photo compression keeps entries small. Swap the two
    `load`/`persist` helpers in `FieldSyncService` if IndexedDB is ever needed.
  - Task 3.4 "drag vertex editing": Leaflet `circleMarker`s aren't natively
    draggable, so vertex correction is tap-the-vertex-then-tap-the-new-spot
    (plus Undo). Walk-marking and tap-appending work as specified.
  - Task 2.2 says "multipart upload"; the endpoint accepts multipart AND
    base64-JSON (`Base64ImageField`, the pattern the player submission photo
    already uses). The SPA and the offline queue use base64-JSON.
- **No new config knobs**, so `OVERRIDABLE_CONFIG_FIELDS` untouched. No new
  Python or npm dependencies. `angular.json`: added `leaflet` to the staff
  app's `allowedCommonJsDependencies` (was already in its styles).
- **Merge conflict hotspots**: `game/admin_api.py` (serializers + tower/zone
  viewsets), `game/tests.py` (appended ~380 lines), `game/models.py` (Tower
  field, new model, `Collection.can_author`), `game/admin.py`,
  `game/migrations/0026_*` numbering, `staff-api.service.ts`,
  `app.routes.ts`/`app.html`, `shared/public-api.ts`, `angular.json`.
- The submission serializer check order was NOT touched.
