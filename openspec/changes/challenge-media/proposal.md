## Why

A Challenge is a single `text` field, so every challenge has to be a question about the player's surroundings written as prose. That makes the whole game one kind of puzzle — read the description, look around, find the thing.

Media changes what a challenge can *be*. A challenge assigned to a tower no longer has to be *about* that tower: "spot the five differences between these two pictures" is a real puzzle, bound to a tower, that has nothing to do with what is standing in front of you. The player still walks there and still submits there — but the content is self-contained, and that is a category of challenge the game cannot express today.

## What Changes

- Add a `ChallengeMedia` model: one or more media items belonging to a Challenge, each with a kind (`IMAGE`, `AUDIO`, `VIDEO`), a file, an optional caption, alt text, and an explicit display order. Follows the existing `TowerPhoto`→`Tower` pattern.
- Add a multipart upload endpoint covering all three kinds. The existing base64 image path stays for its current callers; video and audio never travel as base64.
- Validate on upload: per-kind MIME allowlist, per-kind size ceiling, and duration ceiling for audio and video. Reject rather than transcode.
- Store through Django's storage API with `MEDIA_ROOT` as the shipped default, so switching to S3-compatible object storage is a settings change rather than a code change. **No new infrastructure is required to ship this.**
- **Staff app**: the challenge create/edit form gains media — upload, reorder, caption, set alt text, remove.
- **Player app**: the challenge card renders its media inline — images in a gallery, audio and video with native controls — instead of only `{{ c.text }}`.
- Media inherits challenge visibility: when the server withholds a challenge, it withholds the media and its URLs with it.

Media is the **prompt** side of a challenge. The challenge-type system already governs the **answer** side (what a submission must supply), and this change does not touch it: a spot-the-difference challenge presents two images and still takes a text answer.

## Capabilities

### New Capabilities

- `challenge-media`: media on a challenge — upload, validation, storage, ordering, delivery, and its authoring and player rendering.

### Modified Capabilities

- `challenges`: a Challenge MAY carry ordered media alongside its text; the challenges API reports it.

## Impact

- **Code**: `game/models.py` (`ChallengeMedia` + migration), `game/api.py` (`ChallengeSummarySerializer` gains media; visibility gating), `game/admin_api.py` (media CRUD + multipart upload), `game/serializers.py`, `frontend/projects/staff/src/app/admin/challenges.component.ts`, `frontend/projects/player/src/app/tower/tower-detail.component.ts`.
- **Data**: one new table. No change to `Challenge`'s existing columns; a challenge with no media behaves exactly as today.
- **Settings**: per-kind size/duration/MIME ceilings, and a documented object-storage configuration that is off by default.
- **Dependencies**: a media probe for duration (audio/video). `django-storages` only when object storage is switched on.
- **Out of scope**: transcoding, thumbnail generation, subtitle/caption tracks, media on *answers* (submissions already carry a photo), any change to proximity or presence rules, and MCP authoring of media — an LLM cannot produce real files, so `suggest_challenge` stays text-only for now.
