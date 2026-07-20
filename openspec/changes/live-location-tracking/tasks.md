## 1. Location config on Game and Session

- [ ] 1.1 Add location config fields to `organize.Game`: `location_tracking_enabled` (bool, default `False`), `location_ping_interval_seconds` (positive int, default `30`), `location_visibility` (choices `NONE`/`OWN_TEAM`/`EVERYONE`, default `OWN_TEAM`), `location_retention_days` (positive int, default `30`), `location_consent_text` (text, optional).
- [ ] 1.2 Add nullable per-Session override fields mirroring the Game knobs on `organize.Session`, plus an `effective_location_*` resolver (Session override wins, else Game default) matching the existing config pattern.
- [ ] 1.3 Surface effective location config on the Game/Session serializers and `GET /api/current-session/`; migrations (additive, defaulting tracking OFF).

## 2. LocationPing & LocationConsent models

- [ ] 2.1 Add `game.LocationPing` (`user`, `session`, nullable `team`, `point` PointField, `accuracy`, `recorded_at`, `received_at`) with an index on `(session, user, recorded_at)`; admin + migration.
- [ ] 2.2 Add `game.LocationConsent` (`user`, `session`, `agreed_at`, and a snapshot/hash of the consent text version agreed to) with a uniqueness guard per `(user, session)`; admin + migration.
- [ ] 2.3 Add a `latest_per_user` query helper (most recent ping per user in a Session) for the live feed.

## 3. Consent gate

- [ ] 3.1 `GET /api/location/consent/`: report whether the current user has standing consent for their current Session and return the effective `location_consent_text`.
- [ ] 3.2 `POST /api/location/consent/`: record a `LocationConsent` row for `(user, current session)` with the agreed text version; support withdrawal (`DELETE` or a flag) that revokes consent.
- [ ] 3.3 Enforce that, when the effective config has tracking enabled, a player without standing consent is blocked from playing (joining/submitting) with a clear, actionable error.

## 4. Streaming, live feed, and replay APIs

- [ ] 4.1 `POST /api/location/ping/`: accept `point`, `accuracy`, and client `recorded_at`; reject when tracking is disabled or consent is missing; stamp `received_at`; denormalize `team`.
- [ ] 4.2 `GET /api/location/live/`: return the latest visible position per player/team for the caller's current Session, filtered strictly by effective `location_visibility` (NONE yields none to players; staff always sees all).
- [ ] 4.3 Staff `GET /api/staff/sessions/{id}/location-history/`: return the `LocationPing` series for a Session (filterable by user/team/time window) for after-game replay/analysis.

## 5. Retention & privacy

- [ ] 5.1 Add a `purge_location_pings` management command (schedulable) that deletes pings older than the effective `location_retention_days` and deletes a user's Session pings when consent is withdrawn.
- [ ] 5.2 Ensure deactivating/finishing a Session leaves its pings intact until the retention window expires (history for analysis), and document the retention/consent behavior in the rules text.

## 6. Frontend

- [ ] 6.1 Player app: a location-consent gate on the rules/join flow for location-enabled games (show the game's rules, require agreement, allow withdrawal).
- [ ] 6.2 Player app: a geolocation streaming service that reads the effective `location_ping_interval_seconds` and streams pings at that cadence (no player-facing frequency control), pausing when consent is absent or tracking is off.
- [ ] 6.3 Player app: a live map overlay of visible players/teams from `GET /api/location/live/`, respecting the effective `location_visibility`.
- [ ] 6.4 Staff app: a minimal Session location-history view backed by the replay feed.

## 7. Tests

- [ ] 7.1 Config resolution: effective location knobs resolve Session override → Game default; defaults leave tracking OFF and reject pings.
- [ ] 7.2 Consent gate: a player without standing consent cannot ping or play a location-enabled game; recording consent unblocks; withdrawal re-blocks and purges their Session pings.
- [ ] 7.3 Ping ingestion: a consented player's ping is stored with `team` denormalized and both timestamps; pings are rejected when tracking is disabled.
- [ ] 7.4 Visibility: `/api/location/live/` returns positions only per the effective `location_visibility` (NONE hides from players, OWN_TEAM limits to team, EVERYONE broadens); staff always sees all.
- [ ] 7.5 Retention: the purge command deletes pings past `location_retention_days` and on consent withdrawal, and leaves in-window history intact after a Session ends.
