## 1. Togetherness & visibility config knobs

- [x] 1.1 Add `togetherness_mode` (choices `SPLIT_ALLOWED`/`WHOLE_TEAM_TOGETHER`, default `SPLIT_ALLOWED`) to `organize.Game` with a nullable override on `organize.Session`.
- [x] 1.2 Add `teammate_visibility_mode` (choices `OWN_TEAM`/`EVERYONE`/`SELECT_COUNT`, default `OWN_TEAM`) and `teammate_visibility_count` (PositiveInt, default `0`) to `Game` with nullable `Session` overrides.
- [x] 1.3 Add `presence_window_seconds` (PositiveInt, default `0`) to `Game` with a nullable `Session` override.
- [x] 1.4 Register all four field names in `OVERRIDABLE_CONFIG_FIELDS` and confirm they resolve through `Session.effective(field)`; one schema migration with backward-compatible defaults.

## 2. PresenceRequirement & Challenge wiring

- [x] 2.1 Add `game.PresenceRequirement` (`name`, `min_members_present` PositiveInt default `1`, `method` choices `GEOFENCE`/`PHOTO`/`GEOFENCE_OR_PHOTO` default `GEOFENCE`, nullable `geofence_radius_meters`, nullable `window_seconds`) + admin.
- [x] 2.2 Add nullable `Challenge.presence_requirement` FK (`on_delete=SET_NULL`); `NULL` means no presence requirement.
- [x] 2.3 Validate `PresenceRequirement`: `min_members_present >= 1`, non-negative radius/window when set.

## 3. Effective presence resolver

- [x] 3.1 Add `resolve_presence(session, challenge, tower)` returning the effective `{min_members, method, geofence_radius_meters, window_seconds}`.
- [x] 3.2 When the Session's effective `togetherness_mode == WHOLE_TEAM_TOGETHER`, raise `min_members` to the submitting team's active-membership count (override any challenge `min_members_present`).
- [x] 3.3 Fall back radius → tower effective `proximity_meters`; window → Session effective `presence_window_seconds`; a `NULL` requirement resolves to `{min_members: 1, GEOFENCE, tower proximity, session window}`.

## 4. Presence evaluation service

- [x] 4.1 Geofence co-presence: count distinct active teammates (incl. the submitter) whose most recent live-location ping is fresh and inside the geofence; the submitter is counted from their submission GPS even if their ping is stale (reads the `live-location` ping stream).
- [x] 4.2 Continuous-tracking window: when `window_seconds > 0`, require every counted member's pings across the last `window_seconds` to remain inside the geofence (trajectory/duration); use the window to smooth GPS error.
- [x] 4.3 Photo fallback: when `method == PHOTO`, or `method == GEOFENCE_OR_PHOTO` and geofence/window data is insufficient, accept a submitted photo of the required people as evidence and force staff review (never auto-confirm).
- [x] 4.4 Produce a result: `satisfied` bool + reason code (`INSUFFICIENT_MEMBERS_PRESENT`, `MEMBER_OUTSIDE_GEOFENCE`, `PRESENCE_WINDOW_NOT_SATISFIED`, `PHOTO_REVIEW_REQUIRED`) + the set of verified member ids.
- [x] 4.5 Degrade gracefully: when live-location is unavailable, evaluate point-in-time geofence only (or the photo fallback) and record that the window could not be evaluated.

## 5. Submission integration (challenge-submission)

- [x] 5.1 After the existing submitter-proximity check, invoke the presence evaluation on `POST /api/team_tower_challenges/`; reject with the specific reason code when unsatisfied (and no photo fallback applies).
- [x] 5.2 Add `game.PresenceCheck` linked to `TeamTowerChallenge` recording the resolved requirement, verified member ids, method used, and whether the window was satisfied; write it on every presence-gated submission.
- [x] 5.3 Surface the `PresenceCheck` evidence (present-vs-required, method, window outcome, photo) on the staff review surface.
- [x] 5.4 Confirm the no-op path: a challenge with `presence_requirement = NULL` in a `SPLIT_ALLOWED` game with window `0` submits exactly as base behaviour, writing no blocking `PresenceCheck` failure.

## 6. Teammate visibility wiring & APIs

- [x] 6.1 Expose the resolved `teammate_visibility_mode`/`count` so the `live-location` plotting reads it (own-team / everyone / nearest-N); this change owns the config, live-location owns the plotting.
- [x] 6.2 `GET/POST/PATCH/DELETE /api/staff/presence-requirements/`; accept `presence_requirement` on the challenge editor; accept the four presence knobs on staff Games/Sessions endpoints.
- [x] 6.3 Player-facing read for the current tower: required member count, currently-present member count, and whether a photo fallback is offered.

## 7. Frontend

- [x] 7.1 Staff Game/Session editor: togetherness mode, teammate-visibility mode + count, and continuous-tracking window inputs.
- [x] 7.2 Staff challenge editor: attach/detach a `PresenceRequirement` (min members, method, radius, window).
- [x] 7.3 Player app: show required-vs-present members before submit, live update as teammates arrive, and the photo-fallback capture when the method allows.

## 8. Tests

- [x] 8.1 Config resolution: each of the four knobs resolves Session-override-wins-else-Game-default via `Session.effective`.
- [x] 8.2 Effective resolver: `WHOLE_TEAM_TOGETHER` raises `min_members` to active team size; `SPLIT_ALLOWED` uses the challenge `min_members_present`; radius/window fallbacks apply; `NULL` requirement resolves to the default no-op requirement.
- [x] 8.3 Geofence co-presence: submission with `min_members_present=2` passes with two teammates inside the geofence and is rejected `INSUFFICIENT_MEMBERS_PRESENT` with only one; `MEMBER_OUTSIDE_GEOFENCE` when a required member's ping is outside.
- [x] 8.4 Window verification: a member who stayed inside for the whole window passes; a member who was inside only at the last instant fails `PRESENCE_WINDOW_NOT_SATISFIED`; GPS jitter within the geofence still passes.
- [x] 8.5 Photo fallback: `PHOTO`/`GEOFENCE_OR_PHOTO` routes to `PENDING` staff review and never auto-confirms; `PresenceCheck` records method `PHOTO`.
- [x] 8.6 Backward compatibility: a `NULL`-requirement challenge in a default game submits identically to pre-change behaviour (regression).
- [x] 8.7 Degradation: with live-location unavailable and a window configured, the check falls back to point-in-time and records the window as not-evaluated.
- [x] 8.8 Evidence: `PresenceCheck` persists verified member ids and is exposed on the staff review payload.

## Implementation notes

- **Resolver signature (3.1):** `resolve_presence(session, challenge, tower, team=None)` —
  one extra `team` kwarg vs the task's sketch, because the WHOLE_TEAM_TOGETHER raise
  (task 3.2) needs the submitting team's active-membership count. The result dict carries
  `is_noop`: True only for the fully-default resolution (no `PresenceRequirement`,
  SPLIT_ALLOWED, window 0) — that path skips evaluation entirely and writes no
  `PresenceCheck`, keeping unconfigured games byte-identical (regression-tested).
- **Submission check order (5.1):** presence is evaluated in
  `TeamTowerChallengeSerializer.validate` immediately AFTER the submitter's GPS
  proximity check and BEFORE the team-roles gate: membership → location consent →
  tower/RFID → proximity → **presence** → role gate → pause → lockout. Rationale:
  presence extends the proximity check to teammates, so "too far" wins over "team not
  together", which wins over "missing role". Rejections are 400s carrying
  `{'presence': {'reason_code', 'required_members', 'present_members', 'method'}}`.
- **PresenceCheck writes (5.2):** written for every presence-gated submission that is
  *stored* (accepted or photo-held). A hard-rejected attempt creates no
  `TeamTowerChallenge` row, so it cannot carry a `PresenceCheck` — the reason code
  surfaces in the API error instead. `verified_member_ids` holds auth-user ids.
- **Freshness bound:** a member's latest ping counts as fresh within
  `max(3 × effective location_ping_interval_seconds, 60s)` (`game/presence.py`).
- **Window semantics (4.2):** a member's trajectory = pings inside the window PLUS the
  last ping before the window start (boundary), so "arrived only at the last instant"
  fails. Members with no window data degrade to point-in-time (not punished); if the
  final verified count still meets the requirement after dropping window-failers, the
  submission passes (window_satisfied records the counted members' outcome). With
  live-location unavailable (tracking off / no pings), `window_satisfied` stays NULL —
  "could not be evaluated" (task 4.5).
- **Photo fallback (4.3):** PHOTO or GEOFENCE_OR_PHOTO-with-insufficient-geofence +
  attached photo ⇒ submission stored PENDING with `_presence` hold — auto-confirm is
  suppressed **including the RFID path**. PHOTO with no photo ⇒ 400
  `PHOTO_REVIEW_REQUIRED` asking for one. GEOFENCE_OR_PHOTO with no photo ⇒ 400 with
  the geofence reason + a hint that a photo is accepted.
- **Teammate-visibility precedence (6.1, coordinated with live-location):**
  `location_visibility` (live-location) stays the authoritative coarse gate — NONE is a
  kill switch, OWN_TEAM/EVERYONE decide breadth. `teammate_visibility_mode` refines
  *within* that: SELECT_COUNT narrows to the caller + their N nearest (anchored on the
  caller's own latest ping; recency order if they have none); OWN_TEAM/EVERYONE add no
  further restriction because the OWN_TEAM/EVERYONE split is already layer 1's decision
  (both defaults align, so unconfigured behavior is unchanged and the live-location
  spec's "EVERYONE broadens" scenario still holds). The more restrictive layer always
  wins — SELECT_COUNT never widens past the location gate (tested). The live feed
  response now exposes `teammate_visibility: {mode, count}`.
- **PresenceRequirement is global (2.1):** no `game` FK — the spec models it as a
  named, reusable row shared across challenge banks; the staff CRUD is therefore
  unscoped (`/api/staff/presence-requirements/`). Scoping per game would need a spec
  change.
- **Player presence status (6.3):** `GET /api/towers/{id}/state/` gains a nullable
  `presence` block ({required, present, method, photo_fallback_offered, radius,
  window}); the present count is a point-in-time fresh-ping read (no submission GPS
  yet). The player tower page polls it every 10s while a requirement applies.
- **Frontend (7.x):** staff Game rules panel + Session overrides get the four knobs;
  the Challenges page gains a presence-requirements management card + a per-challenge
  attach/detach select; the review queue shows the `presence_check` evidence block
  (present-vs-required, method, window outcome, weak-photo warning, verified ids).
- **Merge-conflict hotspots:** same files as live-location-tracking (this branch stacks
  on it): `organize/models.py`, `game/models.py`, `game/serializers.py`,
  `game/admin_api.py`, `game/api.py`, `game/location_api.py`, `geogame/urls.py`, shared
  Angular services, staff games/session-detail/challenges/pending-queue components.
  Migrations: `organize/0019_presence_config`, `game/0027_presence_requirement_check`.
