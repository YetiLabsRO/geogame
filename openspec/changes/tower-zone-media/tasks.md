# Tasks — media on towers and zones

## 1. Model and migration

- [ ] 1.1 `game.MediaAsset`: nullable `tower`, nullable `zone`, `kind` (IMAGE/AUDIO/VIDEO), `file`, `caption`, nullable `duration_seconds`, `byte_size`, `captured_by`, `captured_at`, ordering newest-first.
- [ ] 1.2 `CheckConstraint` enforcing exactly one of `tower` / `zone` — at the database, so bulk creates and migrations cannot bypass it.
- [ ] 1.3 Data migration: every `TowerPhoto` → `MediaAsset(kind=IMAGE)` carrying the same `file` path, caption, capturer and timestamp. No file moves. Reversible.
- [ ] 1.4 Drop `TowerPhoto`; move the Django admin inline to `MediaAsset` on both Tower and Zone.
- [ ] 1.5 Tests: the constraint rejects both-set and neither-set; deleting a subject cascades; recollecting geometry does not touch media; the migration preserves file paths and metadata.

## 2. Bounds

- [ ] 2.1 Per-kind size caps and a video duration cap in settings, with documented defaults.
- [ ] 2.2 Server-side validation of kind, content type, size and duration.
- [ ] 2.3 A rejection names the limit it exceeded.
- [ ] 2.4 Tests for each limit, and that an unsupported content type is refused rather than stored.

## 3. API

- [ ] 3.1 `POST/GET /api/staff/towers/{id}/media/` and `/api/staff/zones/{id}/media/`; `DELETE .../media/{id}/`.
- [ ] 3.2 Accept multipart and base64 data URLs, so a queued offline item replays as JSON.
- [ ] 3.3 `AdminTowerSerializer.photos` → `media`; `AdminZoneSerializer` gains `media`.
- [ ] 3.4 Reference media and player submission photos never appear in each other's listings — asserted, not assumed.
- [ ] 3.5 Authoring gate (`Collection.can_author`) applies to media writes as it does to geometry.

## 4. Offline queue on IndexedDB

- [ ] 4.1 Replace the `localStorage` persistence layer with IndexedDB storing `Blob`s.
- [ ] 4.2 Keep queue semantics identical: FIFO replay, local-id → server-id remap, nothing dropped until confirmed, failures kept with their reason.
- [ ] 4.3 One-time migration of any queue already in `localStorage` on a curator's device, so an upgrade mid-trip does not strand captures.
- [ ] 4.4 Encode to base64 at send time, not at queue time.
- [ ] 4.5 Tests: a video-sized blob queues and replays; a rejected item stays queued with its reason; an existing `localStorage` queue is carried over.
- [ ] 4.6 Confirm the size test fails against the `localStorage` implementation — the point of the change is the quota, so the test must be sensitive to it.

## 5. Field capture

- [ ] 5.1 Audio note: hold to record via `MediaRecorder`, showing elapsed time.
- [ ] 5.2 Video: duration-capped capture that stops itself at the limit.
- [ ] 5.3 Media strip on the tower panel and, newly, on the zone panel: what is attached, with removal.
- [ ] 5.4 Zones become a media subject throughout the mode.
- [ ] 5.5 Degrade honestly where `MediaRecorder` is unavailable — offer what the device supports rather than a control that does nothing.

## 6. Verification

- [ ] 6.1 `ruff check .` clean.
- [ ] 6.2 Backend suite and coverage gate clean.
- [ ] 6.3 Frontend suite clean; both apps build.
- [ ] 6.4 Confirm the data migration against a database holding real `TowerPhoto` rows, and that the files still resolve afterwards.
- [ ] 6.5 Browser: attach a photo and an audio note to a tower and to a zone; confirm both appear and replay.
