## Context

`game.Challenge` carries `text`, `difficulty`, a tower binding, and the type-system fields. Media appears twice elsewhere in the codebase and both are useful precedent:

- `TowerPhoto` — a related model with an `ImageField`, a caption, and `ordering`, so a Tower can have many reference photos. This is the shape challenge media wants.
- `TeamTowerChallenge.photo` — a player's *answer*, uploaded through `Base64ImageField`. Explicitly not what this change touches.

The player-facing payload is `ChallengeSummarySerializer` in `game/api.py`, which already withholds `validation_code` from players and is skipped entirely when `challenge_hidden` is set by the tower-visibility rules. Both facts constrain how media is delivered.

The MCP authoring server's governing principle, already in the `mcp-authoring` spec, is that the LLM "composes new games only from valid existing options" — read tools enumerate what exists, and staged operations reference it. Media attachment is designed to obey that principle rather than carve an exception in it.

## Goals / Non-Goals

**Goals:**

- A Challenge can present one or more images, audio clips, or video clips, in a creator-controlled order.
- Media uploaded once can be reused across challenges in the same Game.
- An LLM can compose multi-modal challenges from a catalog of what the creator already uploaded.
- Storage is swappable to object storage by configuration, with no code change and no new infrastructure required to ship.

**Non-Goals:**

- Transcoding, thumbnailing, or any media processing beyond probing and validating.
- Captions/subtitle tracks (distinct from the `caption` text label) and audio descriptions.
- Media on submissions — answers already carry a photo.
- Any path where an LLM supplies a URL the server then fetches.

## Decisions

### A related `ChallengeMedia` model, not fields on Challenge

"One or more" rules out `image`/`audio`/`video` columns. `ChallengeMedia` carries `kind`, `file`, `caption`, `alt_text`, `order`, and provenance (`uploaded_by`, `uploaded_at`), mirroring `TowerPhoto`.

`order` is explicit and integer, not creation order: a creator reordering a gallery is a normal edit, and relying on `id` would make reordering impossible without deleting and re-uploading.

### A library keyed to the Game, with a many-to-many to Challenge

*Alternative considered:* a straight FK from `ChallengeMedia` to `Challenge`, exactly like `TowerPhoto`→`Tower`. Simpler, and it was the first design. Rejected because the MCP case breaks it: an LLM staging twelve challenges that all reference one recording of the town bells would otherwise need twelve copies of the file, and the reviewer would have to approve twelve uploads of the same bytes.

So media belongs to a **Game**, and Challenge↔media is a through-model carrying `order` and the optional per-use `caption`. The same recording can mean different things in two challenges, so the caption lives on the *use*, not the file; `alt_text` describes the file itself and lives with it.

This also makes the MCP read tool coherent: `list_media(game_id)` is a catalog of reusable assets, which is precisely the "valid existing options" shape the spec already requires.

### Multipart upload, and base64 stays where it is

Audio and video make base64 untenable: a 50MB clip becomes ~67MB of JSON held in memory to decode. A multipart endpoint streams to storage instead.

The existing `Base64ImageField` path is left alone rather than migrated. It serves tower photos and submission photos, both of which are small, both of which work, and neither of which is in this change's scope. Two upload mechanisms is a real cost, but it is smaller than a migration of working code this change has no other reason to touch.

### Validate and reject; never transcode

Per-kind MIME allowlist, byte ceiling, and (audio/video) duration ceiling, all settings. An oversized or wrong-format file is rejected at upload with a message naming the limit.

*Alternative considered:* transcoding on upload to normalize formats. Rejected for this change — it needs ffmpeg in the deployment, a job queue, and a pending/ready state machine on every media item, none of which the game needs before it has any media at all. Rejecting with a clear limit is honest and cheap; transcoding can come later without changing the model.

Duration probing still needs to read container metadata. This is the one new dependency, and it is read-only.

### Storage via the Django storage API, local by default

Files go through `default_storage`, so `MEDIA_ROOT` today and an S3-compatible backend later is a `STORAGES` setting plus `django-storages`, with no model or view change. The object-storage path will be documented and tested against the same interface, but stays off by default so this ships with no new infrastructure.

The trade-off worth stating: local `MEDIA_ROOT` on a container filesystem does not survive a rebuild without a mounted volume, and video makes that hurt sooner than photos did. The deployment note belongs with this change even though the default does not change.

### The LLM references library ids and nothing else

`suggest_challenge` accepts `media=[<library id>, …]`. Staging validates that every id exists in the target Game's library and is inside the creator's scope; the apply engine re-checks, as it does for every other reference.

*Alternatives considered and rejected:*

- **LLM supplies a URL, engine fetches.** The most autonomous option and the most dangerous: it turns the apply engine into a server-side fetcher driven by model output — an SSRF sink pointed at whatever the model emits, reachable through an approval flow a human may well rubber-stamp. It also introduces failure states (unreachable, wrong type, moved) at *apply* time, long after review. Not worth it.
- **LLM stages a media brief a human fills.** Safe, and genuinely useful as a future addition, but on its own it means no staged challenge is ever complete — every one carries homework. Library references produce finished, playable challenges immediately.

### Media inherits challenge visibility

When `challenge_hidden` is set, the server already omits the whole challenge payload, so media is withheld with it and no URL is emitted. The requirement is stated explicitly anyway, because the failure mode is silent and severe: a file URL in an unhidden field is a spoiler that leaks the challenge to anyone watching network traffic, defeating hidden-until-arrival without any visible symptom.

## Risks / Trade-offs

- **Video on a phone over rural data** → media is delivered by URL with native player controls and `preload="none"`, so a clip is fetched when the player chooses to play it rather than on card render. Size ceilings keep the worst case bounded.

- **A creator uploads a 200MB video and hits the ceiling mid-game-prep** → the limit is enforced and named at upload time with the actual ceiling in the message, not discovered at play time.

- **Deleting a library item that challenges still use** → deletion is refused while uses exist, and the error names the challenges. Detaching is a separate, explicit action. Silently cascading would empty challenges mid-session.

- **Orphaned files after a challenge is deleted** → the file belongs to the Game's library, not the Challenge, so deleting a challenge detaches rather than deletes. Reclaiming unused library items is a deliberate creator action.

- **Two upload mechanisms in the codebase** (base64 for the old paths, multipart for media) → accepted, and documented above. The alternative was migrating working code outside this change's scope.

- **Alt text is optional, so most media will ship without it** → the authoring form prompts for it per item and the player renders it when present. Making it mandatory would be the stronger choice; it is not made here because it would block a creator mid-flow on a field they cannot always write meaningfully for audio. Worth revisiting.

## Migration Plan

One migration creating the library table and the through table. Nothing on `Challenge` changes, and a challenge with no media serializes and renders exactly as it does today, so the change is additive and needs no backfill.

Rollback drops both tables; challenges revert to text-only with no data loss on `Challenge` itself. Uploaded files under `MEDIA_ROOT` are not removed by the rollback and would need a manual sweep.

## Open Questions

- Should the per-use `caption` fall back to the library item's own label when the creator leaves it blank, or render nothing? Falling back is friendlier; rendering nothing is more predictable. Leaning fallback.
- Is a per-Game library the right scope, or should media be shareable across a creator's Games (like Collections are for geometry)? Per-Game is simpler and matches how challenges are scoped today; a creator running the same course in two towns would want the wider scope. Starting per-Game.
- Should `suggest_challenge` be allowed to attach media the LLM has not "seen" via `list_media` in the same session? No mechanism enforces that today, and it is probably not worth building one.
