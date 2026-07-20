## Why

Runners want to see where teams and players actually are — live, for strategy and safety during the run, and after the fact for analysis ("who did what and where"). Today the app only knows a player's position at the instant they submit near a tower; there is no continuous track. This change lets a consenting player stream their live location to the server so it can be plotted on the map and stored as a `LocationPing` history for replay. Because continuous location is sensitive, tracking is **off by default**, the update frequency is a **game-level** battery/power tradeoff that individual players cannot change, and **consent to the game's location rules is required to play** a location-enabled game.

## What Changes

- Add a `game.LocationPing` history model (`user`, `session`, optional `team`, `point`, `accuracy`, client `recorded_at`, server `received_at`) capturing a player's position over time for live plotting and after-game replay/analysis.
- Add a `game.LocationConsent` record proving a user agreed to a Session's location rules before playing; playing a location-enabled game is gated on it.
- Add game-level location config (default OFF): `location_tracking_enabled`, `location_ping_interval_seconds` (the update frequency — game-level only, not player-changeable), `location_visibility` (NONE / OWN_TEAM / EVERYONE), `location_retention_days`, and `location_consent_text`. Each resolves via the existing Game-default + nullable per-Session-override "effective value" pattern; the runner may override per Session, players never can.
- Add APIs: `POST /api/location/ping/` (stream a position), `GET /api/location/live/` (current visible positions for the map), `GET/POST /api/location/consent/` (read status / record agreement), and a staff `GET /api/staff/sessions/{id}/location-history/` replay feed.
- Player app: a consent gate on the rules/join flow for location-enabled games, background/foreground streaming at the game-configured interval, and a live overlay of visible teammates/players on the map.
- Retention & privacy: pings are personal data — stored only while consent stands and within `location_retention_days`, purged on withdrawal or expiry.

## Capabilities

### New Capabilities
- `live-location`: consented, game-paced streaming of player positions to the server, live plotting per a visibility config, and a stored `LocationPing` history for after-game replay/analysis.

### Modified Capabilities
- `player-app`: the player SPA gains a location-consent gate, live location streaming at the game interval, and a live map overlay of visible players.
- `game-configuration`: a Game configures whether location tracking is on, the update frequency, visibility, retention, and consent text, with per-Session overrides.

## Impact

- **Models**: new `game.LocationPing` and `game.LocationConsent`; new location config fields on `organize.Game` plus nullable per-Session overrides on `organize.Session`.
- **APIs**: new `/api/location/ping/`, `/api/location/live/`, `/api/location/consent/`, and `/api/staff/sessions/{id}/location-history/`; location config surfaced on Game/Session serializers.
- **Frontend**: player app consent gate, a geolocation streaming service paced by the game interval, and a live-positions map layer; staff app gains a replay view (detailed replay UI can land later).
- **Migrations/other**: additive migrations for the two new models and the config fields (all defaulting to tracking OFF); a scheduled/`manage.py` purge task honoring `location_retention_days` and consent withdrawal.
