## Why

A Challenge is a single `text` field. Everything a creator wants to ask — identify this carving, match this birdsong, copy the move in this clip — has to be written as prose, which flattens the game to reading comprehension and wastes the one thing a phone in a town square is good at: showing and playing things.

The MCP authoring server already lets an LLM stage whole banks of challenges with `suggest_challenge` / `suggest_challenges`, and that is the highest-leverage surface it has. But an LLM generating text-only challenges can only produce more prose. Give challenges media and give the LLM a catalog of what the creator has already uploaded, and the same tool starts composing "listen to this, then find where it was recorded" — which is a different game.

## What Changes

- Add a `ChallengeMedia` model: one or more media items per Challenge, each with a kind (`IMAGE`, `AUDIO`, `VIDEO`), a file, an optional caption, alt text, and an explicit display order. Follows the existing `TowerPhoto` pattern (a related model, not fields on the parent).
- Add a creator-scoped **media library**: uploaded items belong to a Game and can be attached to many Challenges, so a recording used by three challenges is stored and reviewed once.
- Add a multipart upload endpoint for all three kinds. The existing base64 image path stays for its current callers; video and audio never travel as base64.
- Validate on upload: per-kind MIME allowlist, per-kind size ceiling, and duration ceiling for audio/video. Reject rather than transcode.
- Store through Django's storage API with `MEDIA_ROOT` as the shipped default, so switching to S3-compatible object storage is a settings change and not a code change. **No new infrastructure is required to ship this.**
- **MCP**: add a `list_media` read tool so the LLM sees the creator's library, and let `suggest_challenge` / `suggest_challenges` attach media **by library id only**. The LLM never uploads, never supplies a URL, and nothing is fetched on its behalf.
- **Staff app**: the challenge create/edit form gains media attachment — upload new or pick from the library, reorder, caption, set alt text, remove.
- **Player app**: the challenge card renders its media inline — images in a gallery, audio and video with native controls — instead of only `{{ c.text }}`.
- Media inherits challenge visibility: when the server withholds a challenge (hidden until arrival), it withholds the media and its URLs with it.

## Capabilities

### New Capabilities

- `challenge-media`: the media library and its upload, validation, storage, ordering, delivery, and the authoring and player rendering of challenge media.

### Modified Capabilities

- `challenges`: a Challenge MAY carry ordered media alongside its text; the challenges API reports it.
- `mcp-authoring`: the read surface gains the media library; `suggest_challenge` accepts library references so an LLM can compose multi-modal challenges.

## Impact

- **Code**: `game/models.py` (`ChallengeMedia`, plus a migration), `game/api.py` (`ChallengeSummarySerializer` gains media; visibility gating), `game/admin_api.py` (library CRUD + multipart upload), `game/serializers.py`, `authoring/tools.py` + `authoring/mcp_server.py` + `authoring/engine.py` (`list_media`, media refs on staged challenges), `frontend/projects/staff/src/app/admin/challenges.component.ts`, `frontend/projects/player/src/app/tower/tower-detail.component.ts`.
- **Data**: one new table. No change to `Challenge`'s existing columns; a challenge with no media behaves exactly as today.
- **Settings**: per-kind size/duration/MIME ceilings, and a documented object-storage configuration that is off by default.
- **Dependencies**: a media probe for duration (audio/video). `django-storages` only when object storage is switched on.
- **Out of scope**: transcoding, thumbnail generation, subtitles/captions tracks, media on *answers* (submissions already carry a photo), and any LLM-supplied URL fetching.
