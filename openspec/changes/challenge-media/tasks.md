## 1. Data model

- [ ] 1.1 Add `game.ChallengeMedia` (challenge FK with `related_name='media'`, `kind` IMAGE/AUDIO/VIDEO, `file`, `caption`, `alt_text`, `order`, `bytes`, `duration_seconds` nullable, `uploaded_by`, `uploaded_at`), ordered by `order`.
- [ ] 1.2 Generate the migration; confirm nothing on `Challenge`'s existing columns changes.
- [ ] 1.3 Deleting a Challenge cascades to its media rows.

## 2. Validation & storage

- [ ] 2.1 Add settings for per-kind MIME allowlists, byte ceilings, and audio/video duration ceilings, with documented defaults.
- [ ] 2.2 Validate kind/MIME/size on upload, rejecting with a message naming the limit and the actual value.
- [ ] 2.3 Probe audio/video duration, store it, enforce the ceiling, and reject files whose duration cannot be determined.
- [ ] 2.4 Write and read every file through `default_storage` (no direct filesystem paths), defaulting to `MEDIA_ROOT`.
- [ ] 2.5 Document the S3-compatible `STORAGES` configuration and the `MEDIA_ROOT`-on-container-rebuild caveat in the deployment docs; keep object storage off by default.

## 3. Upload & media API

- [ ] 3.1 Add a multipart `POST` endpoint for challenge media, streaming the file part to storage (no base64 path for audio/video).
- [ ] 3.2 Add endpoints to list, update (caption/alt text), reorder, and delete a Challenge's media, scoped by `Game.can_edit`.
- [ ] 3.3 Leave the existing `Base64ImageField` paths (tower photos, submission photos) untouched and assert that in a test.

## 4. Challenge payloads

- [ ] 4.1 Add ordered media (kind, URL, caption, alt text) to the staff challenge serializer.
- [ ] 4.2 Add the same to `ChallengeSummarySerializer` for players.
- [ ] 4.3 Ensure a withheld challenge emits no media entries and no media URLs anywhere in the response.
- [ ] 4.4 Keep a challenge with no media serializing byte-identically to today.

## 5. Staff app

- [ ] 5.1 Add a media section to the challenge create/edit form supporting multi-file upload.
- [ ] 5.2 Support reordering, caption, alt text, and removal per item.
- [ ] 5.3 Show upload progress, and on rejection show the reason and limit against the failing file while preserving the rest of the form state.

## 6. Player app

- [ ] 6.1 Render challenge media inline on the challenge card in creator order, alongside the existing text.
- [ ] 6.2 Render images in a gallery; render audio and video with native controls and `preload="none"`.
- [ ] 6.3 Apply captions visibly and alt text to assistive technology.
- [ ] 6.4 Leave a media-less challenge card visually unchanged.

## 7. Tests

- [ ] 7.1 Upload accepts each kind; oversized, over-length, disallowed-MIME, and undeterminable-duration uploads are rejected with the limit named and create no row.
- [ ] 7.2 A challenge carrying several items returns them in order; reordering persists and round-trips without re-upload.
- [ ] 7.3 Order is preserved across mixed kinds.
- [ ] 7.4 Media authoring is creator-scoped; another creator's Game is refused.
- [ ] 7.5 Deleting a challenge deletes its media rows.
- [ ] 7.6 A withheld challenge's response contains no media entry and no media URL — assert against the full serialized response, not just the media field.
- [ ] 7.7 A challenge with no media serializes exactly as before.
- [ ] 7.8 A tower-bound media challenge is served and submitted under the same proximity rules as any other tower challenge.
- [ ] 7.9 Existing base64 tower-photo and submission-photo uploads still work.

## 8. Verification

- [ ] 8.1 `coverage run manage.py test game organize simulator authoring --noinput` passes; `coverage report --fail-under=80` holds.
- [ ] 8.2 `ruff check .` is clean.
- [ ] 8.3 Frontend builds for both player and staff apps.
- [ ] 8.4 `openspec validate challenge-media --type change --strict` passes.
- [ ] 8.5 Manually verify a two-image spot-the-difference challenge, one audio and one video challenge end to end in the player app.
