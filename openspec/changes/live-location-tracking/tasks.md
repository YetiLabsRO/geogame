## 1. Location config on Game and Session

- [x] 1.1 Add location config fields to `organize.Game`: `location_tracking_enabled` (bool, default `False`), `location_ping_interval_seconds` (positive int, default `30`), `location_visibility` (choices `NONE`/`OWN_TEAM`/`EVERYONE`, default `OWN_TEAM`), `location_retention_days` (positive int, default `30`), `location_consent_text` (text, optional).
- [x] 1.2 Add nullable per-Session override fields mirroring the Game knobs on `organize.Session`, plus an `effective_location_*` resolver (Session override wins, else Game default) matching the existing config pattern.
- [x] 1.3 Surface effective location config on the Game/Session serializers and `GET /api/current-session/`; migrations (additive, defaulting tracking OFF).

## 2. LocationPing & LocationConsent models

- [x] 2.1 Add `game.LocationPing` (`user`, `session`, nullable `team`, `point` PointField, `accuracy`, `recorded_at`, `received_at`) with an index on `(session, user, recorded_at)`; admin + migration.
- [x] 2.2 Add `game.LocationConsent` (`user`, `session`, `agreed_at`, and a snapshot/hash of the consent text version agreed to) with a uniqueness guard per `(user, session)`; admin + migration.
- [x] 2.3 Add a `latest_per_user` query helper (most recent ping per user in a Session) for the live feed.

## 3. Consent gate

- [x] 3.1 `GET /api/location/consent/`: report whether the current user has standing consent for their current Session and return the effective `location_consent_text`.
- [x] 3.2 `POST /api/location/consent/`: record a `LocationConsent` row for `(user, current session)` with the agreed text version; support withdrawal (`DELETE` or a flag) that revokes consent.
- [x] 3.3 Enforce that, when the effective config has tracking enabled, a player without standing consent is blocked from playing (joining/submitting) with a clear, actionable error.

## 4. Streaming, live feed, and replay APIs

- [x] 4.1 `POST /api/location/ping/`: accept `point`, `accuracy`, and client `recorded_at`; reject when tracking is disabled or consent is missing; stamp `received_at`; denormalize `team`.
- [x] 4.2 `GET /api/location/live/`: return the latest visible position per player/team for the caller's current Session, filtered strictly by effective `location_visibility` (NONE yields none to players; staff always sees all).
- [x] 4.3 Staff `GET /api/staff/sessions/{id}/location-history/`: return the `LocationPing` series for a Session (filterable by user/team/time window) for after-game replay/analysis.

## 5. Retention & privacy

- [x] 5.1 Add a `purge_location_pings` management command (schedulable) that deletes pings older than the effective `location_retention_days` and deletes a user's Session pings when consent is withdrawn.
- [x] 5.2 Ensure deactivating/finishing a Session leaves its pings intact until the retention window expires (history for analysis), and document the retention/consent behavior in the rules text.

## 6. Frontend

- [x] 6.1 Player app: a location-consent gate on the rules/join flow for location-enabled games (show the game's rules, require agreement, allow withdrawal).
- [x] 6.2 Player app: a geolocation streaming service that reads the effective `location_ping_interval_seconds` and streams pings at that cadence (no player-facing frequency control), pausing when consent is absent or tracking is off.
- [x] 6.3 Player app: a live map overlay of visible players/teams from `GET /api/location/live/`, respecting the effective `location_visibility`.
- [x] 6.4 Staff app: a minimal Session location-history view backed by the replay feed.

## 7. Tests

- [x] 7.1 Config resolution: effective location knobs resolve Session override → Game default; defaults leave tracking OFF and reject pings.
- [x] 7.2 Consent gate: a player without standing consent cannot ping or play a location-enabled game; recording consent unblocks; withdrawal re-blocks and purges their Session pings.
- [x] 7.3 Ping ingestion: a consented player's ping is stored with `team` denormalized and both timestamps; pings are rejected when tracking is disabled.
- [x] 7.4 Visibility: `/api/location/live/` returns positions only per the effective `location_visibility` (NONE hides from players, OWN_TEAM limits to team, EVERYONE broadens); staff always sees all.
- [x] 7.5 Retention: the purge command deletes pings past `location_retention_days` and on consent withdrawal, and leaves in-window history intact after a Session ends.

## Implementation notes

- **Effective-value pattern, not bespoke resolvers (1.2):** the five location knobs are
  registered in `OVERRIDABLE_CONFIG_FIELDS` and resolve through the existing
  `Session.effective(field)` — no separate `effective_location_*` helpers were added.
  `game/location_api.py` wraps it only in `tracking_enabled(session)`.
- **Consent gate scope (3.3):** "blocked from playing" is enforced where gameplay data
  flows: `POST /api/location/ping/` (403) and the submission serializer (403 with an
  actionable message naming `POST /api/location/consent/`). Joining/being placed on a
  team is deliberately NOT blocked so rosters can form before the consent screen; the
  player app redirects to `/location-consent` before the map for a location-enabled
  session, so the flow gates play in practice. The consent check sits in
  `TeamTowerChallengeSerializer.validate` right after the membership check — documented
  check order: membership → **location consent** → tower/RFID → GPS proximity →
  presence (presence-rules) → role gate → pause → lockout.
- **Consent model:** one row per `(user, session)`; withdrawal stamps `withdrawn_at`
  (kept for audit) and synchronously purges that user's session pings; re-granting
  reuses the row with a fresh `agreed_at` + text snapshot/sha256 hash.
- **Retention (5.1/5.2):** `purge_location_pings` deletes per-session pings older than
  the effective `location_retention_days` AND any ping whose user lacks standing
  consent (safety-net re-sweep). Finishing a session does not purge. The retention /
  withdrawal explanation shown to players lives on the consent screen
  (`location-consent.component.ts`), not the static rules page.
- **Frontend:** `LocationStreamService` (player) paces `navigator.geolocation` reads at
  the effective interval — no player-facing frequency control; it stops on 403/409 ping
  responses. Map polls `/api/location/live/` at max(10s, interval) and renders team-colored
  dot markers. Staff replay wireframe at `/sessions/:id/locations` (table + user/team/time
  filters); a scrubber UI is future work.
- **Precedence with presence-rules:** `location_visibility` is the authoritative coarse
  gate (NONE = kill switch; OWN_TEAM/EVERYONE decide breadth); the presence-rules
  `teammate_visibility_mode` only narrows further (SELECT_COUNT nearest-N). See the
  presence-rules implementation notes.
- **Merge-conflict hotspots:** `organize/models.py` (OVERRIDABLE_CONFIG_FIELDS + Game/
  Session fields), `game/models.py` (new models at the end of the PauseWindow section),
  `game/serializers.py` (validate check order), `geogame/urls.py`, `game/admin.py`,
  `game/admin_api.py` (Game/Session serializer field lists), `organize/api.py`
  (CurrentSessionSerializer), shared Angular API services. Migrations:
  `organize/0018_location_config`, `game/0026_location_ping_consent` (numbering
  conflicts with parallel branches expected).
