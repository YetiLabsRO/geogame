# Tasks — field authoring made usable outdoors

## 1. Placement is a point the curator sets

- [x] 1.1 A draggable pin is the placement, starting at the device fix. Remove the crosshair, the `mapCentre` signal and their CSS.
- [x] 1.2 Tapping the map in tower mode moves the pin. (Zone mode keeps tapping for vertices; one mode, one meaning.)
- [x] 1.3 The device's own position stays visibly distinct from the pin — different shape, not merely different colour, because they coincide by default.
- [x] 1.4 "Use my location" returns the pin to the device fix and re-reads it.
- [x] 1.5 The offset chip keeps saying how far the pin sits from the reading.
- [x] 1.6 Tests: the distance helper already has them. The pin-is-the-point rule is `placed() ?? fix()` — unit-testing `??` proves nothing, so it is verified in the browser (6.4) instead, and this line says so rather than pretending otherwise.

## 2. Refreshing the fix

- [x] 2.1 The accuracy badge becomes the refresh control, available in every mode, not only inside a capture.
- [x] 2.2 It shows that a read is in flight, and the resulting accuracy.

## 3. The map shows the collection

- [x] 3.1 Default the target Collection instead of leaving it null; remember the last one used on the device.
- [x] 3.2 Draw its towers and zones whenever one is active, including on first load.
- [x] 3.3 Keep existing content muted so it cannot be mistaken for the capture in hand.

## 4. Zone and tower as equals; a collection from the field

- [x] 4.1 "Drop tower" and "Draw zone" become equally weighted entry actions.
- [x] 4.2 Adjusting an existing zone stays available but stops competing with creating one.
- [x] 4.3 Create a Collection from field mode; it becomes the active target.
- [x] 4.4 The create control says what a Collection is for, since this is the screen where someone meets one first.

## 5. A starting vocabulary

- [x] 5.1 Data migration seeding Building, Place, Square, Statue, Art installation, Fountain, Church — **only when no types exist**. Reversible, and the reverse removes only what it created.
- [x] 5.2 Icons and colours chosen so the set is legible as chips at a glance.
- [x] 5.3 Tests: seeds into an empty table; leaves a populated one untouched; a curator's edits survive re-running migrations.
- [x] 5.4 Replace the development fixtures in `geogame_dev` with the seeded set.
- [x] 5.5 Rename the two test fixtures that borrowed `fountain`, and the creation test that slugified to `church`. They collided with the shipped set — the fixtures move, not the set, because a test that borrows a slug the system ships breaks the day the system ships one.

## 6. Verification

- [x] 6.1 `ruff check .` clean.
- [x] 6.2 Backend suite and coverage gate clean.
- [x] 6.3 Frontend suite clean; both apps build.
- [x] 6.4 Browser: place a tower by tapping, drag it, return it to the device position, refresh the fix; confirm the collection's content is drawn from first load; create a collection and file a tower into it.
