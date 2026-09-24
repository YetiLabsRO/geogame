## Context

`game.Challenge` carries `text`, `difficulty`, a tower binding, and the type-system fields. Media appears twice elsewhere in the codebase, and both are instructive:

- `TowerPhoto` — a related model with an `ImageField`, a caption, and `ordering`, so a Tower can have many reference photos. This is the shape challenge media wants.
- `TeamTowerChallenge.photo` — a player's *answer*, uploaded through `Base64ImageField`. Explicitly not what this change touches.

The player-facing payload is `ChallengeSummarySerializer` in `game/api.py`, which already withholds `validation_code` from players and is skipped entirely when `challenge_hidden` is set by the tower-visibility rules. Both facts constrain how media is delivered.

The motivating case is a challenge assigned to a tower whose content is not about that tower — spot the difference between two pictures. The player still travels to the tower and still submits from there; only the puzzle is self-contained. Nothing about proximity, presence, or tower locking changes.

## Goals / Non-Goals

**Goals:**

- A Challenge can present one or more images, audio clips, or video clips, in a creator-controlled order.
- A challenge's media is its own content, authored and edited with it.
- Storage is swappable to object storage by configuration, with no code change and no new infrastructure required to ship.

**Non-Goals:**

- Transcoding, thumbnailing, or any processing beyond probing and validating.
- Captions/subtitle tracks (distinct from the `caption` label) and audio descriptions.
- Media on submissions — answers already carry a photo.
- Any change to proximity, presence, or tower-locking rules.
- MCP authoring of media (see below).

## Decisions

### Media belongs to the Challenge

`ChallengeMedia` has an FK to `Challenge`, exactly as `TowerPhoto` has one to `Tower`. A challenge's media is its content: the two pictures in a spot-the-difference puzzle *are* the challenge, and they will never be used by another one.

*Alternative considered and rejected:* a per-Game media **library** with a through model, so one recording could be attached to many challenges. This was the first design here, and it was wrong. It optimised for a reuse case that nobody asked for, and it made the primary case worse — authoring a two-picture puzzle would mean uploading two files into a Game-wide catalog, attaching them, and leaving behind two entries that clutter that catalog forever despite never being reused. The indirection cost every challenge something to benefit a case that may not exist.

If reuse turns out to matter later, a `reusable` flag or a copy-from-existing affordance can be added without changing this model. Starting from the simple shape leaves that open; starting from the library did not leave the simple shape open.

`order` is an explicit integer, not creation order: reordering a gallery is a normal edit, and relying on `id` would make it impossible without deleting and re-uploading. For spot-the-difference specifically, which image is first is part of the puzzle.

### Multipart upload, and base64 stays where it is

Audio and video make base64 untenable: a 50MB clip becomes ~67MB of JSON held in memory to decode. A multipart endpoint streams to storage instead.

The existing `Base64ImageField` path is left alone rather than migrated. It serves tower photos and submission photos, both small, both working, neither in this change's scope. Two upload mechanisms is a real cost, but smaller than migrating working code this change has no other reason to touch.

### Validate and reject; never transcode

Per-kind MIME allowlist, byte ceiling, and (audio/video) duration ceiling, all settings. An oversized or wrong-format file is rejected at upload with a message naming the limit and the actual value.

*Alternative considered:* transcoding on upload to normalise formats. Rejected for this change — it needs ffmpeg in the deployment, a job queue, and a pending/ready state machine on every media item, none of which the game needs before it has any media at all. Rejecting with a clear limit is honest and cheap; transcoding can be added later without changing the model.

Duration probing still needs to read container metadata. This is the one new dependency, and it is read-only.

### Storage via the Django storage API, local by default

Files go through `default_storage`, so `MEDIA_ROOT` today and an S3-compatible backend later is a `STORAGES` setting plus `django-storages`, with no model or view change. The object-storage path will be documented and tested against the same interface, but stays off by default so this ships with no new infrastructure.

The trade-off worth stating: local `MEDIA_ROOT` on a container filesystem does not survive a rebuild without a mounted volume, and video makes that hurt sooner than photos did. The deployment note belongs with this change even though the default does not change.

### No MCP media authoring in this change

`suggest_challenge` stays text-only. An LLM cannot produce a real image or recording, so every option for giving it media authority is a workaround: referencing a shared library (which this change no longer has), staging a brief for a human to fill (which leaves every staged challenge carrying homework), or supplying a URL the server fetches (which turns the apply engine into an SSRF sink driven by model output, behind an approval a human may rubber-stamp).

None of those is worth building before the human authoring flow exists and there is something real to learn from. The LLM keeps staging text-only challenge banks exactly as it does today, and a creator adds media afterwards.

### Media inherits challenge visibility

When `challenge_hidden` is set, the server already omits the whole challenge payload, so media is withheld with it and no URL is emitted. The requirement is stated explicitly anyway, because the failure mode is silent and severe: a file URL in an unhidden field is a spoiler that leaks the challenge to anyone watching network traffic, defeating hidden-until-arrival with no visible symptom.

## Risks / Trade-offs

- **Video on a phone over rural data** → media is delivered by URL with native controls and `preload="none"`, so a clip is fetched when the player chooses to play it rather than on card render. Size ceilings keep the worst case bounded.

- **A creator uploads a 200MB video and hits the ceiling mid-prep** → the limit is enforced and named at upload with the actual value, not discovered at play time.

- **Deleting a challenge deletes its media** → correct here, since the media is that challenge's content, but it means an accidental challenge deletion loses the files. Ordinary deletion confirmation covers it; nothing is shared, so nothing else breaks.

- **No reuse path at all** → a creator who genuinely wants one clip on three challenges must upload it three times. Accepted deliberately; see the library discussion above. If this becomes a real complaint it is an additive change, not a rewrite.

- **Two upload mechanisms in the codebase** → accepted and documented above.

- **Alt text is optional, so most media will ship without it** → the authoring form prompts per item and the player renders it when present. Mandatory would be the stronger choice; it is not made here because it would block a creator mid-flow on a field they cannot always write meaningfully for audio. Worth revisiting.

## Migration Plan

One migration creating the media table. Nothing on `Challenge` changes, and a challenge with no media serialises and renders exactly as today, so the change is additive and needs no backfill.

Rollback drops the table; challenges revert to text-only with no data loss on `Challenge` itself. Uploaded files under `MEDIA_ROOT` are not removed by the rollback and would need a manual sweep.

## Open Questions

- Should a blank `caption` render nothing, or fall back to something derived (filename, kind)? Rendering nothing is more predictable and probably right for a puzzle where a stray label could give the answer away.
- Should there be a per-challenge cap on the number of media items, separate from the per-file ceilings? A challenge with forty images is a broken challenge, but the number is arbitrary and easy to add later.
