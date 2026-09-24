## Why

Field mode works and is awkward to use, in ways that only show up standing outside with one hand free.

**You cannot say where the tower goes.** The placement is the map centre, drawn as a crosshair. To move the point you pan the map under it. That was a deliberate choice — it keeps the thing being positioned out from under the thumb doing the positioning — but it means the only way to put a tower on the doorway you are looking at is to drag the whole map until the doorway is dead centre. And when you have not panned, the crosshair, the pending tower pin and the blue "you are here" dot are three indicators stacked on one point, which reads as one muddled blob rather than as "this is you, that is the tower".

**The map is empty.** The target Collection's towers and zones are drawn — but only once a Collection is picked, and nothing picks one. A curator opens field mode, sees bare streets, and has no way to tell whether they already recorded this fountain last month. That was the exact failure the field map was given memory to prevent.

**A zone is a second-class action.** "Drop tower here" is a full-width primary button; "New zone" is half-width and shares its row with a dropdown. Walking a boundary is not a lesser act of authoring than dropping a pin, and the buttons say it is.

**A wander has nowhere to go.** Everything must be filed into a Collection that already exists. Someone setting out to scout a new town has to stop, go to another screen, make a Collection, and come back.

**There is no vocabulary.** A fresh install ships zero Tower types. The three visible in development — Church, Fountain, Landmark tree — are fixtures left behind by verification, not a designed set, and they have been mistaken for one.

## What Changes

- **The pin is the placement.** A draggable pin starts at the device fix; tapping the map moves it; dragging fine-tunes it. The crosshair goes, because with tap-to-place it is a second way to set one point and it is the indicator that was overlapping the other two.
- **Refresh the fix from the device at any time**, not only from inside a capture — the accuracy badge is the only thing on screen claiming to know where you are, and it must be able to say so again.
- **Draw the target Collection's content whenever there is one**, and default to a Collection rather than to none, remembering the last one used.
- **Tower and zone become equal entry actions.**
- **Create a Collection from field mode**, so a scouting trip can begin with one action instead of a detour.
- **Seed a starter Tower-type vocabulary** — Building, Place, Square, Statue, Art installation, Fountain, Church — for an install that has none.

## Capabilities

### Modified Capabilities
- `field-authoring`: placement becomes an explicit point the curator sets rather than the map centre; the target Collection's existing content is always drawn; zones become an equal entry action; a Collection can be created in the field.
- `tower-types`: an install begins with a vocabulary rather than with nothing.

## Impact

- **Frontend**: `field-mode.component.ts` — placement, map click handling, the idle panel, an inline Collection form, a persisted target Collection. The crosshair CSS and the `mapCentre` signal go with the crosshair.
- **Backend**: one data migration seeding `TowerType` rows **only when the table is empty**, so it cannot disturb an install that has built its own vocabulary. `POST /api/staff/collections/` already exists; no new endpoints.
- **Reversal, stated plainly**: this undoes the crosshair introduced by `library-map-curation`. That change replaced drag-to-nudge with a crosshair to solve "the target is under the thumb". Tap-to-place solves the same problem differently — you tap where the tower goes, not on the thing you are moving — and it is what the map already does for zone vertices, so field mode stops having two different ideas about what tapping the map means.
- **Non-goal**: opening an *existing* element from the field map to edit it. That is `library-map-curation` 4.3–4.5 and belongs there.
