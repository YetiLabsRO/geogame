## Why

Today every active tower is drawn on every player's map and every challenge is legible from afar, so there is no exploration, no fog-of-war, and no way to hide an objective until a team physically finds it. Creators want richer discovery: a tower a team must walk up to before it appears, a whole area that has to be roamed before it un-fogs, and challenges that are either teased from a distance or concealed until arrival. These two ideas are orthogonal — *whether a tower is on the map* and *whether its challenge is legible* — so they compose into a clean two-axis model. Discovery must be tracked **per team**: a team keeps seeing what it has found even after a rival conquers it or it goes ownerless, and whether a team can see *other* teams' conquests is itself a rule the creator sets.

## What Changes

- Add **AXIS 1 — tower discoverability** as a per-tower enum with a game-wide default: `HIDDEN` (the tower is not drawn until a team walks within proximity and it pops up), `VISIBLE` (always on the map — the default, preserving current behavior), and `FOG_REVEAL` (neither the zone nor the tower is known; a team reveals a FOG_REVEAL tower by entering its zone **or** by covering more than a configurable percentage of the zone).
- Add **AXIS 2 — challenge visibility** as a per-tower enum with a game-wide default: `HIDDEN_UNTIL_ARRIVAL` (the challenge is concealed until the player is inside the tower's activation area) and `VISIBLE_ANYWHERE` (the challenge is legible from any distance but can only be completed inside the activation area — the default, preserving current behavior).
- Add a per-zone **fog-of-war reveal threshold** (`fog_reveal_coverage_pct`) with a game default, driving how much of a `FOG_REVEAL` zone a team must cover to reveal it.
- Add per-team **`game.TowerDiscovery`** records that persist a `(session, team, tower)` discovery — surviving conquest by another team and periods with no owner — plus the reveal mechanism (proximity for `HIDDEN`, zone entry / coverage for `FOG_REVEAL`) and a discovery-evaluation ping endpoint.
- Add a per-game **`reveal_other_teams_ownership`** setting controlling whether the public map shows where *other* teams conquered (default `True`, preserving current behavior).
- Filter `GET /api/towers/` and `GET /api/zones/` to what the caller's team may currently see, and colour ownership subject to `reveal_other_teams_ownership`.
- Player-app UX: hidden towers pop up on approach, a fog overlay clears as a team roams, and the tower detail page reveals/enables the challenge per its challenge-visibility axis.
- Everything defaults to fully-visible / no-fog / show-all-ownership, so existing games are unchanged.

## Capabilities

### New Capabilities
- `tower-visibility`: the two-axis visibility model (tower discoverability × challenge visibility), per-tower overrides with game-wide defaults, the per-zone fog reveal threshold, the other-teams-ownership setting, and effective-value resolution.
- `discovery-tracking`: per-team `TowerDiscovery` records, the reveal mechanism (proximity, zone entry, zone coverage), the discovery ping endpoint, and the "towers this team has discovered" query.

### Modified Capabilities
- `geographic-map`: the towers/zones API is filtered to what the caller's team may see and colours ownership per the game's other-teams-ownership setting.
- `player-app`: the map renders only team-visible geometry with a discovery/fog UX, and the tower detail page gates the challenge by its challenge-visibility axis.

## Impact

- **Models**: new `game.TowerDiscovery` (`session`, `team`, `tower`, `discovered_at`, `discovered_by`, `method`); new fields `Tower.discoverability` (nullable), `Tower.challenge_visibility` (nullable), `Zone.fog_reveal_coverage_pct` (nullable); new `Game` defaults `tower_discoverability_default`, `challenge_visibility_default`, `fog_reveal_coverage_pct_default`, `reveal_other_teams_ownership` (with nullable per-Session overrides per the config pattern).
- **APIs**: `GET /api/towers/` and `GET /api/zones/` become team-visibility-filtered; new `POST /api/discovery/ping/` (report position, return newly revealed towers) and `GET /api/discovery/towers/` (this team's discovered towers); staff config surfaces for the new knobs.
- **Frontend**: player map gains discovery pop-ups and a fog-of-war overlay; tower detail gates challenge legibility; staff/creator editors expose the per-tower/per-zone/per-game visibility knobs.
- **Migrations/other**: additive schema; a data migration backfilling the new defaults to `VISIBLE` / `VISIBLE_ANYWHERE` / `reveal_other_teams_ownership=True` so migrated games behave exactly as before. Zone-coverage computation consumes the position stream from the `live-location` capability, with the discovery ping as a fallback source.
