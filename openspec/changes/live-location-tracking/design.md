## Context

The game already reads a device's GPS position at submission time to enforce `proximity_meters`, but it keeps no continuous track. Runners have asked for two things: a live picture of where teams are during a run (strategy, and keeping an eye on players), and an after-game record to analyse who went where. Both require streaming positions to the server and storing them.

Continuous location is the most sensitive data the platform touches, so the design is deliberately conservative: tracking is off unless a Game turns it on, the sampling rate is a single game-level knob (a battery/power tradeoff the organiser owns, not a per-player setting), and a player must explicitly agree to the game's location rules before they can play a location-enabled game. Storage is bounded by a retention window and tied to standing consent.

This change owns the transport (streaming, storage, live feed) and the consent gate. The richer question of *who may see whom* — own-team vs everyone vs "N nearest people" — and using a live track to verify presence for challenges are deferred to the `presence-rules` change, which builds on the `LocationPing` history introduced here. Push-based delivery of live positions (websockets) is layered on by `realtime-and-notifications`; this change ships with polling as the baseline.

## Goals / Non-Goals

**Goals:**
- Let a consenting player stream their position to the server at a game-configured cadence.
- Store a `LocationPing` history suitable for live plotting and after-game replay/analysis.
- Make location tracking opt-in per Game and off by default; make the update frequency game-level and not player-changeable.
- Require and record consent to the game's location rules as a precondition of playing a location-enabled game.
- Bound retention of personal location data and honor consent withdrawal.

**Non-Goals:**
- The detailed teammate-visibility model (own-team / everyone / N people) and presence-verified challenges — those are `presence-rules`; this change ships a coarse `location_visibility` enum only.
- Websocket/push delivery of live positions — `realtime-and-notifications` supersedes the polling baseline.
- A polished replay/scrubber UI — the API and a minimal staff view land here; the timeline UI can follow.
- Geofencing, trajectory anti-spoofing, or duration checks (also `presence-rules`).

## Decisions

- **Store an append-only `LocationPing` history rather than only a "last known position."** A history serves both live plotting (read the latest per user) and after-game replay (read the series). Alternative considered: a single mutable `last_location` per membership — rejected because it cannot support replay/analysis, the stated second use case.
- **`LocationPing` lives in the `game` app** (`user`, `session`, nullable denormalized `team`, `point` PointField, `accuracy` in meters, client `recorded_at`, server `received_at`), indexed on `(session, user, recorded_at)` for both "latest per user" and per-user time-series reads. It matches the batch's naming (`game.LocationPing`).
- **Frequency is a single game-level knob, `location_ping_interval_seconds`.** It resolves via the existing Game-default + nullable per-Session-override effective-value pattern (the runner may override per Session), but there is **no player-facing control** — the app reads the effective interval and paces itself. Rationale: sampling rate is a battery/power tradeoff the organiser owns, and a uniform rate keeps tracks comparable. Alternative considered: per-player frequency — rejected as stated in the requirement and because it fragments the data.
- **Consent is an explicit, recorded act, modeled as `game.LocationConsent`** (`user`, `session`, `agreed_at`, and a snapshot/hash of the `location_consent_text` version agreed to). Playing a location-enabled game is gated on a current consent row. Alternative considered: a boolean flag on the membership — rejected because it does not capture *what* was agreed to or *when*, which retention and audit need.
- **Tracking defaults OFF.** All new config defaults preserve today's behavior: `location_tracking_enabled=False`. When false, no consent is required, no pings are accepted, and the app never streams.
- **Coarse visibility enum now, rich model later.** `location_visibility` ∈ {NONE, OWN_TEAM, EVERYONE} controls whether live positions are shown to others (NONE = stored for after-game only). The `presence-rules` change refines this; the `live-location` capability cross-references it.
- **Retention is bounded and consent-tied.** `location_retention_days` caps how long pings are kept; a purge task deletes pings past the window and deletes a user's pings for a Session when they withdraw consent.

## Risks / Trade-offs

- [Continuous location is sensitive personal data] → off by default; explicit recorded consent required to play; bounded retention; deletion on withdrawal; visibility defaults to own-team, never broader than the Game configures.
- [High-frequency pings could flood the DB and drain batteries] → the frequency is a single organiser-owned knob with a sane default (e.g. 30s), the app coalesces/queues while offline, and `received_at` lets the server drop absurdly stale or duplicated samples.
- [A player withdraws consent mid-run] → withdrawal immediately stops streaming and blocks continued play of a location-mandatory game; their pings for that Session are purged; the runner sees them drop off live plotting.
- [Spoofed positions] → out of scope here (trajectory/geofencing anti-spoofing is `presence-rules`); `accuracy` and server `received_at` are stored so later verification and analysis can reason about quality.
- [Live overlay could leak positions beyond what the Game allows] → the `/api/location/live/` feed filters strictly by the effective `location_visibility` and the caller's team; NONE yields no live positions to anyone but staff.

## Migration Plan

1. Add `game.LocationPing` and `game.LocationConsent` models and their migrations (additive; no backfill).
2. Add location config fields to `organize.Game` (all defaulting to tracking OFF) and nullable override fields to `organize.Session`; add an effective-value resolver reusing the existing pattern.
3. Ship the ping/live/consent APIs and the staff location-history feed; gate ping acceptance and play on a current consent row when tracking is enabled.
4. Add a purge management command (schedulable) honoring `location_retention_days` and consent withdrawal.
5. Player app: consent gate + streaming service + live overlay, all no-ops when the effective config has tracking OFF.
