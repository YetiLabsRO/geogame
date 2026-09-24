## 1. Data model

- [ ] 1.1 Add `game.ChallengeMedia` (game FK, `kind` IMAGE/AUDIO/VIDEO, `file`, `alt_text`, `bytes`, `duration_seconds` nullable, `uploaded_by`, `uploaded_at`) as the per-Game library item.
- [ ] 1.2 Add the `ChallengeMediaUse` through model (challenge FK, media FK, `order`, per-use `caption`) with `unique_together` on (challenge, media) and ordering by `order`.
- [ ] 1.3 Wire `Challenge.media = ManyToManyField(ChallengeMedia, through=ChallengeMediaUse, blank=True)`.
- [ ] 1.4 Generate the migration; confirm nothing on `Challenge`'s existing columns changes.
- [ ] 1.5 Refuse deletion of a `ChallengeMedia` that has uses, naming the challenges; deleting a Challenge removes its uses and retains the library items.

## 2. Validation & storage

- [ ] 2.1 Add settings for per-kind MIME allowlists, byte ceilings, and audio/video duration ceilings, with documented defaults.
- [ ] 2.2 Validate kind/MIME/size on upload, rejecting with a message naming the limit and the actual value.
- [ ] 2.3 Probe audio/video duration on upload, store it, and enforce the duration ceiling; reject unreadable containers rather than storing them.
- [ ] 2.4 Write and read every file through `default_storage` (no direct filesystem paths), defaulting to `MEDIA_ROOT`.
- [ ] 2.5 Document the S3-compatible `STORAGES` configuration and the `MEDIA_ROOT`-on-container-rebuild caveat in the deployment docs; keep object storage off by default.

## 3. Upload & library API

- [ ] 3.1 Add a multipart `POST` endpoint for library uploads, streaming the file part to storage (no base64 path for audio/video).
- [ ] 3.2 Add creator-scoped library list/detail/update/delete endpoints, scoped by `Game.can_edit`.
- [ ] 3.3 Add endpoints to attach, detach, reorder, and caption a Challenge's media.
- [ ] 3.4 Leave the existing `Base64ImageField` paths (tower photos, submission photos) untouched and assert that in a test.

## 4. Challenge payloads

- [ ] 4.1 Add ordered media (kind, URL, caption, alt text) to the staff challenge serializer.
- [ ] 4.2 Add the same to `ChallengeSummarySerializer` for players.
- [ ] 4.3 Ensure a withheld challenge emits no media entries and no media URLs anywhere in the response.
- [ ] 4.4 Keep a challenge with no media serializing byte-identically to today.

## 5. MCP authoring

- [ ] 5.1 Add `AuthoringTools.list_media(game_id)` returning the creator-scoped library (id, kind, alt text, duration).
- [ ] 5.2 Register `list_media` in `authoring/mcp_server.py`.
- [ ] 5.3 Extend `suggest_challenge` / `suggest_challenges` to accept ordered media library ids.
- [ ] 5.4 Validate at stage time that every media id exists, belongs to the target Game, and is in the creator's scope; refuse and name the failing reference otherwise.
- [ ] 5.5 Re-check every media reference in the apply engine and fail the operation rather than apply a dangling attachment.
- [ ] 5.6 Reject any LLM-supplied file, data URI, or URL on a media reference — ids only, no fetching.
- [ ] 5.7 Render challenge media references in the staff proposal diff so a reviewer sees what the LLM attached.

## 6. Staff app

- [ ] 6.1 Add a media section to the challenge create/edit form: upload new, or pick from the Game's library.
- [ ] 6.2 Support reordering, per-use caption, alt text, and removal.
- [ ] 6.3 Show upload progress, and on rejection show the reason and limit against the failing file while preserving the rest of the form state.
- [ ] 6.4 Add a library management view: list, preview, edit alt text, delete (with the in-use refusal surfaced).

## 7. Player app

- [ ] 7.1 Render challenge media inline on the challenge card in creator order, alongside the existing text.
- [ ] 7.2 Render images in a gallery; render audio and video with native controls and `preload="none"`.
- [ ] 7.3 Apply captions visibly and alt text to assistive technology.
- [ ] 7.4 Leave a media-less challenge card visually unchanged.

## 8. Tests

- [ ] 8.1 Library upload accepts each kind; oversized, over-length, and disallowed-MIME uploads are rejected with the limit named and create no row.
- [ ] 8.2 One library item attached to several challenges stores one file and reports per-use captions and orders.
- [ ] 8.3 Reordering persists and round-trips without re-upload.
- [ ] 8.4 Library access and attachment are creator-scoped; another creator's Game is refused.
- [ ] 8.5 Deleting an in-use item is refused and names the challenges; deleting a challenge detaches and retains the items.
- [ ] 8.6 A withheld challenge's response contains no media entry and no media URL — assert against the full serialized response, not just the media field.
- [ ] 8.7 A challenge with no media serializes exactly as before.
- [ ] 8.8 `list_media` is creator-scoped; `suggest_challenge` stages ordered media refs and applies them in order.
- [ ] 8.9 A bad media reference (missing, other Game, out of scope) is refused at stage time and re-checked at apply time.
- [ ] 8.10 A media reference carrying a URL or data URI is refused, and no outbound fetch is attempted.
- [ ] 8.11 Existing base64 tower-photo and submission-photo uploads still work.

## 9. Verification

- [ ] 9.1 `coverage run manage.py test game organize simulator authoring --noinput` passes; `coverage report --fail-under=80` holds.
- [ ] 9.2 `ruff check .` is clean.
- [ ] 9.3 Frontend builds for both player and staff apps.
- [ ] 9.4 `openspec validate challenge-media --type change --strict` passes.
- [ ] 9.5 Manually verify one image, one audio, and one video challenge end to end in the player app.
