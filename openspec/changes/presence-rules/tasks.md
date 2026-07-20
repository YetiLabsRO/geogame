## 1. Togetherness & visibility config knobs

- [ ] 1.1 Add `togetherness_mode` (choices `SPLIT_ALLOWED`/`WHOLE_TEAM_TOGETHER`, default `SPLIT_ALLOWED`) to `organize.Game` with a nullable override on `organize.Session`.
- [ ] 1.2 Add `teammate_visibility_mode` (choices `OWN_TEAM`/`EVERYONE`/`SELECT_COUNT`, default `OWN_TEAM`) and `teammate_visibility_count` (PositiveInt, default `0`) to `Game` with nullable `Session` overrides.
- [ ] 1.3 Add `presence_window_seconds` (PositiveInt, default `0`) to `Game` with a nullable `Session` override.
- [ ] 1.4 Register all four field names in `OVERRIDABLE_CONFIG_FIELDS` and confirm they resolve through `Session.effective(field)`; one schema migration with backward-compatible defaults.

## 2. PresenceRequirement & Challenge wiring

- [ ] 2.1 Add `game.PresenceRequirement` (`name`, `min_members_present` PositiveInt default `1`, `method` choices `GEOFENCE`/`PHOTO`/`GEOFENCE_OR_PHOTO` default `GEOFENCE`, nullable `geofence_radius_meters`, nullable `window_seconds`) + admin.
- [ ] 2.2 Add nullable `Challenge.presence_requirement` FK (`on_delete=SET_NULL`); `NULL` means no presence requirement.
- [ ] 2.3 Validate `PresenceRequirement`: `min_members_present >= 1`, non-negative radius/window when set.

## 3. Effective presence resolver

- [ ] 3.1 Add `resolve_presence(session, challenge, tower)` returning the effective `{min_members, method, geofence_radius_meters, window_seconds}`.
- [ ] 3.2 When the Session's effective `togetherness_mode == WHOLE_TEAM_TOGETHER`, raise `min_members` to the submitting team's active-membership count (override any challenge `min_members_present`).
- [ ] 3.3 Fall back radius → tower effective `proximity_meters`; window → Session effective `presence_window_seconds`; a `NULL` requirement resolves to `{min_members: 1, GEOFENCE, tower proximity, session window}`.

## 4. Presence evaluation service

- [ ] 4.1 Geofence co-presence: count distinct active teammates (incl. the submitter) whose most recent live-location ping is fresh and inside the geofence; the submitter is counted from their submission GPS even if their ping is stale (reads the `live-location` ping stream).
- [ ] 4.2 Continuous-tracking window: when `window_seconds > 0`, require every counted member's pings across the last `window_seconds` to remain inside the geofence (trajectory/duration); use the window to smooth GPS error.
- [ ] 4.3 Photo fallback: when `method == PHOTO`, or `method == GEOFENCE_OR_PHOTO` and geofence/window data is insufficient, accept a submitted photo of the required people as evidence and force staff review (never auto-confirm).
- [ ] 4.4 Produce a result: `satisfied` bool + reason code (`INSUFFICIENT_MEMBERS_PRESENT`, `MEMBER_OUTSIDE_GEOFENCE`, `PRESENCE_WINDOW_NOT_SATISFIED`, `PHOTO_REVIEW_REQUIRED`) + the set of verified member ids.
- [ ] 4.5 Degrade gracefully: when live-location is unavailable, evaluate point-in-time geofence only (or the photo fallback) and record that the window could not be evaluated.

## 5. Submission integration (challenge-submission)

- [ ] 5.1 After the existing submitter-proximity check, invoke the presence evaluation on `POST /api/team_tower_challenges/`; reject with the specific reason code when unsatisfied (and no photo fallback applies).
- [ ] 5.2 Add `game.PresenceCheck` linked to `TeamTowerChallenge` recording the resolved requirement, verified member ids, method used, and whether the window was satisfied; write it on every presence-gated submission.
- [ ] 5.3 Surface the `PresenceCheck` evidence (present-vs-required, method, window outcome, photo) on the staff review surface.
- [ ] 5.4 Confirm the no-op path: a challenge with `presence_requirement = NULL` in a `SPLIT_ALLOWED` game with window `0` submits exactly as base behaviour, writing no blocking `PresenceCheck` failure.

## 6. Teammate visibility wiring & APIs

- [ ] 6.1 Expose the resolved `teammate_visibility_mode`/`count` so the `live-location` plotting reads it (own-team / everyone / nearest-N); this change owns the config, live-location owns the plotting.
- [ ] 6.2 `GET/POST/PATCH/DELETE /api/staff/presence-requirements/`; accept `presence_requirement` on the challenge editor; accept the four presence knobs on staff Games/Sessions endpoints.
- [ ] 6.3 Player-facing read for the current tower: required member count, currently-present member count, and whether a photo fallback is offered.

## 7. Frontend

- [ ] 7.1 Staff Game/Session editor: togetherness mode, teammate-visibility mode + count, and continuous-tracking window inputs.
- [ ] 7.2 Staff challenge editor: attach/detach a `PresenceRequirement` (min members, method, radius, window).
- [ ] 7.3 Player app: show required-vs-present members before submit, live update as teammates arrive, and the photo-fallback capture when the method allows.

## 8. Tests

- [ ] 8.1 Config resolution: each of the four knobs resolves Session-override-wins-else-Game-default via `Session.effective`.
- [ ] 8.2 Effective resolver: `WHOLE_TEAM_TOGETHER` raises `min_members` to active team size; `SPLIT_ALLOWED` uses the challenge `min_members_present`; radius/window fallbacks apply; `NULL` requirement resolves to the default no-op requirement.
- [ ] 8.3 Geofence co-presence: submission with `min_members_present=2` passes with two teammates inside the geofence and is rejected `INSUFFICIENT_MEMBERS_PRESENT` with only one; `MEMBER_OUTSIDE_GEOFENCE` when a required member's ping is outside.
- [ ] 8.4 Window verification: a member who stayed inside for the whole window passes; a member who was inside only at the last instant fails `PRESENCE_WINDOW_NOT_SATISFIED`; GPS jitter within the geofence still passes.
- [ ] 8.5 Photo fallback: `PHOTO`/`GEOFENCE_OR_PHOTO` routes to `PENDING` staff review and never auto-confirms; `PresenceCheck` records method `PHOTO`.
- [ ] 8.6 Backward compatibility: a `NULL`-requirement challenge in a default game submits identically to pre-change behaviour (regression).
- [ ] 8.7 Degradation: with live-location unavailable and a window configured, the check falls back to point-in-time and records the window as not-evaluated.
- [ ] 8.8 Evidence: `PresenceCheck` persists verified member ids and is exposed on the staff review payload.
