# Tasks — the map-first library

## 1. Library feed

- [x] 1.1 `GET /api/staff/library/`: every repository tower (geometry, resolved styling, media count, collection ids) and zone (shape, colour, media count, collection ids), staff-only. `game/library_api.py`, new module rather than another block in `admin_api.py`.
- [x] 1.2 Query it without an N+1 per element — membership and counts come from prefetches, asserted by a query-count test. `select_related` + `prefetch_related` + annotated counts.
- [x] 1.3 Tests: an element in two collections reports both; an element in none reports an empty list; geometry matches the repository rows. Plus an empty-list case for an element in no collection, so the map can ask every pin the same question.

## 2. Library page

- [x] 2.1 `/library`: map of the whole repository, towers by resolved styling, zones as shapes.
- [x] 2.2 Collection selector; members highlighted; counts stated.
- [x] 2.3 Tapping an element toggles its membership in the selected Collection, with the map updating in place.
- [x] 2.4 Inspector: name, type, media count, and every Collection the element belongs to — so "remove" can never be misread as "delete". Names every collection the element is in, so "remove" cannot be misread as "delete".
- [x] 2.5 Side panel list, searchable by name and filterable by tower type, in step with the map; selecting a row brings it into view.
- [x] 2.6 Create a Collection without leaving the page.
- [x] 2.7 Nav entry; `/collections` redirects to `/library`; nav-coverage assertion updated. `/collections` redirects to `/library`. Needed a fix to the nav-coverage assertion, which flagged the redirect as an unlinked destination — a redirect is not a destination, so it is now excluded.
- [x] 2.8 Tests: membership toggle calls add/remove and never a delete; the filter narrows map and list together.

## 3. Crosshair placement

- [x] 3.1 Fixed centre crosshair; the map pans beneath it; the crosshair position is what gets saved.
- [x] 3.2 Live readout of the distance between the chosen point and the device's own fix.
- [x] 3.3 A control returning the point to the current fix.
- [x] 3.4 Marker drag retained; both paths feed the same chosen position, so neither can disagree with what is saved. Marker drag now recentres the map, so pin, crosshair and saved point stay one point rather than three candidates.
- [x] 3.5 Tests for the offset calculation, including that it reads zero at the fix. `field-mode.distance.spec.ts` (5 specs) — including that an eastward offset is scaled by latitude, which ignoring would overstate by ~44% at 46°N.

## 4. Field map memory

- [x] 4.1 Draw the target Collection's existing towers and zones, muted relative to the element being captured.
- [x] 4.2 Redraw when the target Collection changes.
- [ ] 4.3 Selecting an existing element opens it: attach media, attach a challenge, correct its position.
- [ ] 4.4 Position correction on an existing element goes through the same save path as capture, so the offline queue covers it.
- [ ] 4.5 Tests: the overlay follows the collection switcher; editing an existing element queues like a capture when offline.

## 5. Verification

- [x] 5.1 `ruff check .` clean.
- [ ] 5.2 Backend suite and coverage gate clean.
- [x] 5.3 Frontend suite clean; both apps build.
- [x] 5.4 Browser: toggle membership on the map, confirm it persists and the geometry survives removal. Add: 7 members to 8, counts update, button flips to "Remove from". Remove: back to 7 and the tower is still in the library.
- [x] 5.5 Browser: filter a library of mixed types, confirm map and list agree. Searching "oak" leaves 1 pin and 1 row.
- [x] 5.6 Browser at phone width: crosshair placement, offset readout, return-to-fix. At 420x900: crosshair shows "at your position", panning reads "45 m from you", "centre on me" returns it to zero.

## 6. Deferred, with the reason

- [ ] 4.3 / 4.4 / 4.5 — opening an existing element from the field map to attach media, attach a challenge, or correct its position. The overlay renders and the elements are tappable; opening them is the next step. Deferred because the media half belongs to `tower-zone-media`, which is blocked: another session's in-flight `game/bundles.py` imports `TowerPhoto` in five places, and that change removes it.
- [ ] 5.2 Backend suite and coverage gate — running at time of writing.
