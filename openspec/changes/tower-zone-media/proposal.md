## Why

A reference photo is what turns a coordinate into a findable place: it tells a player which of four fountains, and tells the curator six months later what they meant. `TowerPhoto` already does this for towers, and only for towers — a Zone can carry no record of itself at all, though "the meadow behind the church, enter from the north gate" is exactly the kind of thing a curator knows on site and cannot write down.

Some of what a curator knows on site is also badly suited to a photograph. "The marker is behind the left pillar, and the dog in the yard is friendly but loud" is ten seconds of speech and two minutes of typing with cold hands on a phone. A short clip is the only honest way to record an approach or a route.

## What Changes

- Replace `TowerPhoto` with **`MediaAsset`** — the same idea widened to **zones as well as towers**, and to **photos, audio notes and short video** as well as stills.
- **Capture in the field**: camera as now, plus a hold-to-record audio note and a length-capped video clip, all attachable to the tower or zone in hand.
- **Migrate every existing `TowerPhoto`** into the new model in place, keeping its file, caption, capturer and timestamp, so nothing already captured is lost or re-uploaded.
- **Move the offline queue to IndexedDB** and store media as blobs rather than base64 in `localStorage`. This is forced, not incidental: the current queue base64-encodes into a ~5 MB browser quota, which a single video clip exceeds. It also restores the design the field-authoring change originally called for before the shipped code deviated.
- **Bound what may be captured** — per-kind size caps, a video duration cap, and server-side validation of both, so a field upload cannot be a surprise on someone's data plan or a way to fill the disk.

## Capabilities

### New Capabilities
- `tower-media`: what may be attached to a tower or a zone, in what kinds and within what bounds; that an attachment belongs to exactly one subject; and that media survives the geometry being recollected or re-typed.

### Modified Capabilities
- `field-authoring`: field capture gains audio and video alongside photos, gains zones as a capture subject, and its offline queue gains durable blob storage.

## Impact

- **Models**: new `game.MediaAsset` (nullable `tower`, nullable `zone`, exactly-one constraint, `kind`, `file`, `caption`, nullable `duration_seconds`, `byte_size`, `captured_by`, `captured_at`). `game.TowerPhoto` is migrated into it and removed.
- **Data migration**: every `TowerPhoto` becomes a `MediaAsset(kind=IMAGE)` carrying the same stored file path, so no file moves and no upload is repeated. Reversible.
- **Breaking, internally**: `Tower.photos` becomes `Tower.media`, and `AdminTowerSerializer.photos` becomes `media`. The staff SPA is the only consumer; the Django admin inline moves with it.
- **APIs**: `POST/GET /api/staff/towers/{id}/media/` and `/api/staff/zones/{id}/media/`, `DELETE .../media/{id}/`. Accepts multipart or a base64 data URL, as the photo endpoint already does, so a queued offline item replays as JSON.
- **Frontend**: audio capture via `MediaRecorder`, video via a duration-capped file input, a media strip on both tower and zone panels, and a rewritten `FieldSyncService` persistence layer (queue semantics unchanged: FIFO, local-id remap, nothing dropped until the server confirms, failures kept for retry).
- **Storage**: media lands on the same backend as submission photos. Video is the first thing here big enough to be worth watching; the duration and size caps exist so that stays true.
