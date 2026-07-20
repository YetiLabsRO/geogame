## Why

Curators build games by going **into the field**: they walk a town scouting locations, photograph the physical things players must find, and decide where towers and zones belong while standing on the spot. Today the staff app assumes a desk: geometry is entered by typing coordinates or clicking a web map away from the site, and there is no way to capture a tower "where I'm standing", attach a reference photo of the objective, or draw a zone by walking its perimeter. This change adds an on-site **mobile field authoring mode** that lets a curator drop a Tower at their current GPS position, attach photos, draw or adjust a Zone, attach challenges, and file everything into a target Collection — all from a phone in the field, tolerant of poor connectivity.

## What Changes

- Add a **field authoring mode** to the staff SPA, optimized for one-handed, outdoor, on-site mobile use, that targets a Collection (see the `collections` capability introduced by `points-repository-and-collections`).
- **Drop a Tower at the current GPS position** with a single action, showing the reading's accuracy, recording it as capture provenance, and allowing a nudge / re-read / multi-reading average before saving.
- **Attach reference photos** captured from the device camera to a Tower via a new `game.TowerPhoto` model — the authoring reference image that helps players recognise the physical objective (distinct from player challenge submissions).
- **Draw and adjust Zones on site**: append polygon vertices by walking the boundary (a vertex at each current-GPS mark) or by tapping/dragging vertices, and adjust existing zones.
- **Attach challenges in the field**: create or select a Challenge and associate it with a Tower while on location.
- **Add new/adjusted geometry to a target Collection** automatically, with the ability to stage field-created Towers as inactive drafts and activate them later.
- **Offline-tolerant capture and sync**: queue field edits (towers, photos, zones, challenge links) locally when there is no signal and sync them when connectivity returns, surfacing any failures for retry.

## Capabilities

### New Capabilities

- `field-authoring`: an on-site mobile flow for curators to build game elements — drop towers at the current GPS position, attach reference photos, draw/adjust zones, attach challenges, and file everything into a target Collection, tolerant of poor connectivity.

### Modified Capabilities

- `staff-app`: the staff SPA is explicitly usable on both web and mobile, and offers a mobile field authoring mode for on-site game building.

## Impact

- **Models**: new `game.TowerPhoto` (FK `tower`, `image`, optional `caption`, `captured_by`, `captured_at`); optional capture-provenance field `Tower.authored_accuracy_m` (nullable). Reuses the existing `Tower.is_active` flag for draft/publish; adds no new geometry ownership (Collection membership comes from the `collections` capability).
- **APIs**: `/api/staff/towers/` accepts a capture-accuracy value and files new towers into the target Collection; new `POST/GET/DELETE /api/staff/towers/{id}/photos/`; `/api/staff/zones/` accepts walked/tapped vertices and files new zones into the target Collection; a field action to attach a Challenge to a Tower. Authoring is gated to staff authorised to edit the target Collection (see the `game-authoring-roles` capability).
- **Frontend**: new mobile-first field authoring mode in `frontend/projects/staff` — GPS-centered Leaflet map, "drop tower here" control with a live accuracy indicator, camera capture, walk-the-boundary zone drawing, an attach-challenge sheet, a target-Collection selector, and an IndexedDB offline queue with sync-on-reconnect.
- **Migrations/other**: one migration adding `game.TowerPhoto` and `Tower.authored_accuracy_m`; media storage for reference photos. Backward compatible — every addition is opt-in and does not alter existing desk-based authoring.
