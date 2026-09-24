# Design — media on towers and zones

## Decision 1 — one model with two nullable subjects, not two parallel models and not a generic relation

`TowerPhoto` widened to zones has three plausible shapes:

1. **A second `ZonePhoto`** mirroring the first. Minimal, and wrong the moment anything wants "all media captured last Saturday" or a shared upload endpoint — every query and every bit of validation exists twice, and they drift.
2. **A `GenericForeignKey`** over contenttypes. Genuinely polymorphic, and pays for it: no database-level referential integrity, no `select_related`, awkward filtering, and a contenttypes dependency in a model that only ever points at two things.
3. **One model with nullable `tower` and `zone` and a database constraint that exactly one is set.** Real foreign keys, real cascades, ordinary joins, and the "exactly one" rule enforced where it cannot be bypassed.

Three. The constraint is a `CheckConstraint`, not a `clean()`, because bulk creates and the data migration both bypass model validation and the invariant has to hold for them too.

## Decision 2 — migrate `TowerPhoto` in place rather than keeping it alongside

Keeping both would mean two upload paths, two admin inlines and two serializer fields for the same idea, with the older one quietly accumulating rows. So `TowerPhoto` is migrated into `MediaAsset` and removed.

The migration copies `image.name` — the stored relative path — straight into `MediaAsset.file`. **No file moves.** A `FileField` holds a path, so the old `tower_photos/...` entries keep resolving on the same storage; re-homing them would mean copying every file to a new prefix for no benefit and a window where half are missing. New captures land under the new prefix, and the two coexist in storage without anything needing to know.

It is reversible, because a forward migration that cannot be undone on a schema this young is a bad trade for a repository with a few hundred rows.

## Decision 3 — video forces IndexedDB, which is what the queue should have been

The shipped queue persists to `localStorage` as base64 JSON. The original design.md said IndexedDB; the implementation deviated, documented the deviation, and was right at the time — compressed photos are small and `localStorage` is far less machinery.

Video ends that. `localStorage` is a ~5 MB per-origin quota of *strings*, and base64 inflates by about a third, so a single short clip exceeds it. The failure mode is the bad kind: a `QuotaExceededError` thrown at the moment a curator saves, in the field, offline, with nowhere to put the capture that was the entire point of the queue.

So the persistence layer becomes IndexedDB storing `Blob`s. The queue's *semantics* do not change — FIFO replay, local-id → server-id remap so media queued against an unsynced tower follows it, nothing dropped until the server confirms, failures kept with their reason for retry or discard. Only `load`/`persist` change, which the deviation note in the original tasks.md explicitly named as the swap point. The upload path keeps accepting base64 as well as multipart, so a blob is encoded at send time rather than at queue time.

## Decision 4 — bound each kind, and say the bound before the capture rather than after

Limits live in settings with documented defaults: images downscaled on-device as now, audio capped by duration and size, video capped by duration and size. The server validates both, because a client-side cap is a courtesy and not a control.

Two things follow that are easy to get wrong:

- **A rejection must not eat the capture.** If the server refuses a queued item, the item stays in the queue with its reason. A curator who recorded something once, in a place they have walked away from, must not lose it to a validation error.
- **The video control enforces the duration while recording**, stopping at the cap rather than letting someone record two minutes and then be told. The server still checks, for the client that lies.

`duration_seconds` is stored for audio and video. It is what makes a media strip legible — "0:12" on a chip tells a curator whether this is the note about the pillar or the one about the gate — and recomputing it server-side would mean decoding every upload.

## Decision 5 — media belongs to the geometry, not to a collection or a game

Attachments hang off the Tower or Zone, which are repository rows. Recollecting geometry, adding it to a second collection, or pulling it into a game changes nothing about its media; deleting the geometry cascades, because a photo of a place that no longer exists in the library describes nothing.

This is the same reasoning that put the geometry in a repository in the first place, and it is why "which collection was this photo for" is not a question the model can be asked.

## Non-goals

- **Player-facing media.** Whether a reference photo is shown to players, and under what visibility rules, is a game-design question that belongs with `tower-visibility`. This change stores and curates; it does not publish.
- **Transcoding or thumbnails.** Images are downscaled on the device, which is where the bandwidth is worth saving. Server-side derivatives are worth doing when there is a player-facing surface to serve them to.
- **Editing media.** Attach, review, remove. Cropping and trimming are a photo app's job.
