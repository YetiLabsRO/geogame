## Why

Domination today assumes any one player standing near a tower may complete a challenge for the whole team, and there is no way to require that teammates are actually together. Real events want both extremes: some games are meant to be done as a **whole team together**, others deliberately let a team **split up** to cover ground while still counting each split group as a legitimate presence. A challenge should be able to demand a **minimum number of members present** (a team of four splits, but each attempt needs at least two people on the spot). Presence must be verifiable: a single point-in-time GPS fix is easy to spoof, so this change adds **geofencing** as the primary check, a **photo of the required people** as a (deliberately weaker, staff-reviewed) fallback, and — leaning on the live-location stream — a **continuous-tracking window** that verifies a short trajectory/duration inside the geofence, which is far harder to fake and also smooths GPS error. All of it is opt-in: with no configuration, nothing changes.

## What Changes

- Add per-Game **togetherness** config on `organize.Game` (with nullable per-`Session` overrides): `togetherness_mode` = `SPLIT_ALLOWED` (default) or `WHOLE_TEAM_TOGETHER`.
- Add per-Game **teammate map visibility** config: `teammate_visibility_mode` = `OWN_TEAM` (default) / `EVERYONE` / `SELECT_COUNT`, plus `teammate_visibility_count` for the `SELECT_COUNT` case. This config is the source of truth for which other players a player's map plots; the plotting/streaming itself is performed by the `live-location` capability (introduced by the sibling `live-location-tracking` change).
- Add a per-Game **continuous-tracking window** default `presence_window_seconds` (default `0` = point-in-time). All four fields register in `OVERRIDABLE_CONFIG_FIELDS` and resolve through the existing `Session.effective(field)` helper.
- Introduce a `game.PresenceRequirement` model — a reusable requirement a `Challenge` may reference via a nullable FK (`Challenge.presence_requirement`, `NULL` = no requirement): `min_members_present`, `method` (`GEOFENCE` / `PHOTO` / `GEOFENCE_OR_PHOTO`), optional `geofence_radius_meters`, and optional `window_seconds`.
- Define **effective presence resolution**: `WHOLE_TEAM_TOGETHER` raises the required count to the full active team; otherwise the challenge's `min_members_present` (default `1`) applies. Radius falls back to the tower's effective `proximity_meters`; window falls back to the Session's effective `presence_window_seconds`.
- Enforce presence at submission (modifies `challenge-submission`): after the existing submitter-proximity check, the system verifies that the required number of distinct active teammates are co-present inside the geofence, using recent live-location pings; when a window is set it verifies each required member stayed inside for the whole window; a photo fallback is accepted where the method allows and is routed to staff review.
- Record presence evidence on the submission (which members were verified, method used, window satisfied) and surface it to staff review; reject with specific reasons (`INSUFFICIENT_MEMBERS_PRESENT`, `MEMBER_OUTSIDE_GEOFENCE`, `PRESENCE_WINDOW_NOT_SATISFIED`).
- Staff/creator API + Angular UI: edit the game/session presence knobs, attach a `PresenceRequirement` to a challenge, and show players how many members are present vs required before they submit.

## Capabilities

### New Capabilities
- `presence-rules`: per-game team-togetherness and teammate-visibility configuration, per-challenge minimum-members-present requirements, and presence verification via geofencing, photo fallback, and continuous-tracking windows.

### Modified Capabilities
- `challenge-submission`: a submission additionally enforces the challenge's effective presence requirement (minimum members co-present in the geofence, optionally over a continuous window) and records presence evidence for staff review.

### Referenced Capabilities
- `live-location`: introduced by the sibling `live-location-tracking` change. Presence-rules owns the teammate-visibility config and reads the live-location ping stream to evaluate co-presence and continuous-tracking windows; it does not redefine live-location. (see the `live-location` capability)

## Impact

- **Models**: `organize.Game` gains `togetherness_mode` (default `SPLIT_ALLOWED`), `teammate_visibility_mode` (default `OWN_TEAM`), `teammate_visibility_count` (default `0`), `presence_window_seconds` (default `0`); `organize.Session` gains four matching nullable overrides added to `OVERRIDABLE_CONFIG_FIELDS`. New `game.PresenceRequirement`; `game.Challenge` gains nullable `presence_requirement` FK. New `game.PresenceCheck` audit record linked to `game.TeamTowerChallenge` capturing the verified members, method used, and window outcome.
- **APIs**: staff Games/Sessions endpoints accept the four presence knobs; `/api/staff/presence-requirements/` CRUD; the challenge editor accepts `presence_requirement`; submission responses return presence blockers with specific reason codes; the review surface exposes the `PresenceCheck` evidence; a player-facing "who is present vs required" read for the current tower.
- **Frontend**: staff Game/Session editor gains the togetherness, visibility, and window inputs; the challenge editor attaches a presence requirement; the player app shows required-vs-present member counts and the photo-fallback capture when allowed.
- **Migrations/other**: one schema migration adding the four config fields (backward-compatible defaults), the `PresenceRequirement` and `PresenceCheck` tables, and the `Challenge.presence_requirement` FK. No data migration required; every field defaults to today's "no presence requirement" behaviour.
