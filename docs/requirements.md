# Requirements Document

## Introduction

The **geogame** platform is a Django-based location-aware system for scouting events. Teams of scouts compete within a **Game** (the top-level container) — each game has arbitrarily-named **TeamGroups** (e.g. age groups like Exploratori/Temerari/Seniori for one event, arbitrary groupings for others) — by capturing physical **Towers** placed on a map. A tower is conquered by answering a **Challenge** at the tower's real-world location (verified by GPS or RFID tag). Controlling a majority of towers inside a **Zone** grants the zone to the controlling team, which accrues time-based **floating points** toward the team's total score. Staff review challenge submissions from the Django admin.

## Project Structure

The Django project is split across three Python packages:

- **`geogame/`** — project module (settings, root URLconf, WSGI/ASGI). `DJANGO_SETTINGS_MODULE=geogame.settings`.
- **`game/`** — app owning the gameplay core: `Zone`, `Tower`, `Challenge`, `TeamTowerChallenge` (submissions), `TeamTowerOwnership`, `TeamZoneOwnership`.
- **`organize/`** — app owning the social/organizational layer: `Game`, `TeamGroup`, `Team`, `Player`, `TeamPlayer`.

This document describes the **current implemented behavior** of the system as of the `main` branch. Use it as the source of truth when adding or changing features — update requirements first, then plan and tasks.

Target users:
- **Players** (scout teams) — participate via mobile browser using team code
- **Staff / organizers** — review submissions, manage towers/zones/teams via Django admin
- **Administrators** — import KML data, configure scoring, start/end the game

## Requirements

### 1. Geographic Map Model

1.1 **User Story**: As an administrator, I want to define geographic **Zones** (polygons) on a map so that I can group towers and award area-wide bonuses.
   - **Acceptance Criteria**:
     - WHEN a zone is created THEN the system SHALL store a polygon boundary, a human-readable name, a display color, and a score-type strategy.
     - THE system SHALL support four score-type strategies per zone: `LOGARITHMIC`, `EXPONENTIAL`, `LINEAR`, and `BONUS`.
     - THE `BONUS` strategy SHALL be an exponential function capped at 200 points.

1.2 **User Story**: As an administrator, I want to place individual **Towers** (points) inside the map so that teams have physical objectives to capture.
   - **Acceptance Criteria**:
     - WHEN a tower is created THEN the system SHALL store its latitude/longitude as a `PointField`, a name, and optionally associate it with a zone.
     - WHEN a tower is created THEN the system SHALL allow configuring its category: `NORMAL` (GPS-verified capture) or `RFID` (tag-scanned capture).
     - IF a tower is of category `RFID` THEN it SHALL have a unique `rfid_code` used for tag-based capture.
     - A tower SHALL have an `is_active` flag; deactivating SHALL release all of its current team/zone ownerships (see 7.3).
     - A tower SHALL have an `initial_bonus` integer field; the value is awarded to the team as locked points the moment the tower is captured.

1.3 **User Story**: As a player, I want to see a live map of zones and towers colored by current team control so that I can plan my team's moves.
   - **Acceptance Criteria**:
     - THE main map page (`/`) SHALL render all zones and active towers using Leaflet.
     - Zone and tower colors SHALL reflect current ownership by TeamGroup.
     - A score-focused map view SHALL be available at `/map/<team_group_slug>/` for per-group leaderboards.

### 2. Teams and Team Groups

2.1 **User Story**: As an administrator, I want to organize teams into arbitrarily-named **TeamGroups** per Game so that each event can partition teams as needed (e.g. by age group: Exploratori/Temerari/Seniori, or by color, or ad hoc).
   - **Acceptance Criteria**:
     - A **Game** SHALL have zero or more `TeamGroup` rows (organize.TeamGroup). Each TeamGroup has a `name`, a URL-safe `slug`, and is unique per `(game, slug)`.
     - A **Team** (organize.Team) SHALL belong to exactly one Game and (optionally) one TeamGroup within that Game.
     - WHEN a team is created THEN the system SHALL assign a unique `code` used historically by players to authenticate submissions. (This `code` path is retired at Phase 2 launch — see §13.2.)
     - WHEN a team is created THEN the system SHALL allow configuring a display color for map rendering and an optional description.
     - Teams SHALL have a `players` M2M (through `TeamPlayer`) linking to `Player` (1:1 with `User`). Players are not yet exercised by the game flow; full usage lands in Phase 2.

2.2 **User Story**: As a player, I want my team to be scored only against other teams in the same TeamGroup so that competition is fair within a cohort.
   - **Acceptance Criteria**:
     - Tower ownership, zone ownership, and leaderboards SHALL be computed independently per TeamGroup.

### 3. Challenges

3.1 **User Story**: As an administrator, I want to define text-based **Challenges** that teams must solve to capture a tower.
   - **Acceptance Criteria**:
     - A challenge SHALL have text content and a difficulty level (integer, typically 1-5).
     - A challenge SHALL either be bound to a specific tower (tower-specific) or be generic (reusable across any tower).
     - Challenges SHALL be visible and manageable in the Django admin with counts of total attempts and successful confirmations.

3.2 **User Story**: As a player, I want the system to serve me the right "next challenge" for the tower I'm standing at so that progression is structured.
   - **Acceptance Criteria**:
     - WHEN a team requests the next challenge for a tower THEN the system SHALL select, in order: the lowest-difficulty tower-specific challenge not yet conquered, then generic challenges in ascending difficulty, then (once all exhausted) the hardest generic challenge as an infinite replay fallback.
     - THE next-challenge calculation SHALL be based on the highest difficulty the team has already conquered at that tower.

### 4. Challenge Submission & Review

4.1 **User Story**: As a player, I want to submit a challenge attempt from the physical tower location so that my team can prove it completed the task.
   - **Acceptance Criteria**:
     - A submission SHALL include the team code, the tower, the challenge, the submitter's current GPS position, and optionally a photo.
     - THE system SHALL reject the submission if the submitter's GPS position is more than 50 meters from the tower.
     - UPON submission THE system SHALL create a `TeamTowerChallenge` with outcome `PENDING`.

4.2 **User Story**: As a staff member, I want to review pending submissions and confirm or reject them so that captures reflect real achievement.
   - **Acceptance Criteria**:
     - Submissions SHALL have three outcomes: `PENDING`, `CONFIRMED`, `REJECTED`.
     - Review SHALL happen from the Django admin; the admin SHALL record the reviewing staff user (`checked_by`), the `verified_at` timestamp, and an optional `response_text`.
     - The admin SHALL display a `time_diff` (seconds between submission and verification) and expose photo and response text as readonly fields.
     - A `/pending/` page SHALL show the count of pending submissions for staff quick-access.

4.3 **User Story**: As a player, I want a cooldown after a rejected attempt so that guessing is discouraged.
   - **Acceptance Criteria**:
     - IF a team's most recent attempt on a tower was `REJECTED` within the last 5 minutes THEN the system SHALL refuse new submissions from that team on that tower until the cooldown expires.
     - THE tower detail page SHALL indicate when a team is in cooldown.

4.4 **User Story**: As a staff member confirming a challenge, I want the system to automatically capture the tower for that team so that I don't need a second step.
   - **Acceptance Criteria**:
     - WHEN a `TeamTowerChallenge` transitions to `CONFIRMED` THEN the system SHALL invoke `tower.assign_to_team(team)`.
     - Assignment SHALL:
       - Close any prior team's active `TeamTowerOwnership` record for the tower (set `timestamp_end`).
       - Create a new active `TeamTowerOwnership` for the new team (set `timestamp_start`).
       - Award the tower's `initial_bonus` as locked points to the team's `score`.
       - Trigger zone recalculation (see 6.3).

### 5. RFID Tower Capture

5.1 **User Story**: As a player, I want to capture an RFID-tagged tower by scanning it so that physical tag presence is proof enough.
   - **Acceptance Criteria**:
     - THE system SHALL expose a route `/tower/rfid/<rfid_code>/` that resolves to the matching tower.
     - RFID capture SHALL still validate the submitter is within 50 meters of the tower.
     - RFID capture SHALL not require a text challenge and SHALL auto-confirm (outcome=`CONFIRMED`), immediately assigning the tower to the team.

5.2 **User Story**: As a staff member, I want the admin to show the public RFID URL for each RFID tower so that I can generate printable tag stickers.
   - **Acceptance Criteria**: The Tower admin SHALL display a clickable URL built from the tower's `rfid_code` for RFID-category towers.

### 6. Scoring System

6.1 **User Story**: As a player, I want my team to earn points both instantly (for captures) and continuously (for zone control) so that both aggressive play and holding territory are rewarded.
   - **Acceptance Criteria**:
     - Each team SHALL have a `score` (locked points) and a dynamically-computed `floating_score` (points from active zone ownerships).
     - `current_score()` SHALL return `score + floating_score`.

6.2 **User Story**: As an administrator, I want different zones to score at different rates so that I can tune game balance.
   - **Acceptance Criteria**: Zone score functions SHALL be:
     - `LINEAR`: `mins` (1 point per minute held).
     - `LOGARITHMIC`: `30 × ln(mins) + mins² / 10000`.
     - `EXPONENTIAL` / `BONUS`: `min(mins² / 25 + 50, 200)`.
     - `mins` is the duration of the current ownership window in minutes.

6.3 **User Story**: As a player, I want controlling the most active towers in a zone to grant my team that whole zone so that strategy rewards map coverage.
   - **Acceptance Criteria**:
     - Zone control SHALL be computed per TeamGroup as: the team owning a strict majority of the zone's currently-active towers within that group.
     - WHEN tower ownership changes THE system SHALL recompute zone control; on change THE prior owner's `TeamZoneOwnership` SHALL be closed (floating score finalized and added to locked `score`) and a new `TeamZoneOwnership` SHALL be opened for the new controller (if any).

6.4 **User Story**: As an administrator, I want some towers to be worth more on capture so that key towers matter.
   - **Acceptance Criteria**: Capturing a tower SHALL add `tower.initial_bonus` to the capturing team's locked `score`.

### 7. Game State Management

7.1 **User Story**: As a player, I want to see my team's progress on a tower and request my current challenge via the team code so that I don't need an account.
   - **Acceptance Criteria**:
     - `/tower/<id>/` SHALL accept a team code, display whether the team is the current owner, the current pending/cooloff status, and the team's next challenge.
     - `/tower/challenge/` SHALL accept challenge submissions (form-based).

7.2 **User Story**: As a staff member, I want TeamGroup-specific score maps so that I can project leaderboards for each cohort during the event.
   - **Acceptance Criteria**: `/map/<team_group_slug>/` SHALL render a score-focused map showing the named TeamGroup's zone control and team standings. The slug is the TeamGroup's `slug` field (unique per Game).

7.3 **User Story**: As an administrator, I want a way to end or reset the game from the admin so that I can retire the current round cleanly.
   - **Acceptance Criteria**:
     - The Tower admin SHALL expose an `unassign_all` action that closes every active `TeamTowerOwnership` and `TeamZoneOwnership` (treated as an end-of-game action).
     - Deactivating an individual tower (setting `is_active=False`) SHALL close its ownerships and trigger zone recomputation.

### 8. REST API

8.1 **User Story**: As a map frontend, I want to fetch current state over a REST API so that the page can refresh data without a full reload.
   - **Acceptance Criteria**:
     - `GET /api/zones/` SHALL return zones with current per-TeamGroup ownership coloring (GeoJSON via `rest_framework_gis`). An optional `group` query parameter colors by the named TeamGroup.
     - `GET /api/towers/` SHALL return active towers; it SHALL accept optional `lat`, `lng`, and `accuracy` query parameters for proximity filtering.
     - `GET /api/teams/` SHALL return teams (currently exposes the `group` FK; filtering by group is planned for Phase 2A).
     - `GET /api/challenges/` SHALL return challenges (tower-specific and generic).
     - `POST /api/team_tower_challenges/` SHALL accept a challenge submission with team, tower, challenge, location, and optional photo, enforcing the 50-meter proximity check.

### 9. Admin Operations

9.1 **User Story**: As a staff member, I want rich Django admin screens so that I can monitor the game without a custom dashboard.
   - **Acceptance Criteria**:
     - **Zone admin**: color-coded list, shows current per-TeamGroup controller.
     - **Tower admin**: list filterable by zone/active/category (NORMAL vs RFID); shows current owner per TeamGroup; exposes `initial_bonus`, `decrease_initial_bonus`, `rfid_code`, and a public RFID URL. `autocreate_zone` + circle zone is created on save when `zone` is unset.
     - **Team admin**: list filterable by `group` and `game`; shows `score` (readonly) and real-time `floating_score`.
     - **Game admin**: standard CRUD for `organize.Game` with start/end times and is_active flag. `TeamGroup` admin exists via smart_selects chained dropdowns (Team.group depends on Team.game).
     - **Challenge admin**: shows counts of total attempts and successful confirmations per challenge.
     - **TeamTowerChallenge admin**: list filterable by outcome, submitter, reviewer; shows photo, response text, verified timestamp, and time-to-verify as readonly columns.

### 10. Data Import

10.1 **User Story**: As an administrator, I want to seed zones and towers from KML files exported from Google Earth so that map authoring stays outside the app.
   - **Acceptance Criteria**:
     - THE `import_data` management command SHALL parse `zone_normal.kml`, `zone_bonus.kml`, and `puncte.kml` to populate Zones and Towers.
     - THE command SHALL delete and recreate Zone/Tower data on each run (idempotent-by-replacement, not by merge).

### 11. Deployment & Infrastructure

11.1 **User Story**: As an administrator, I want the PostGIS extension installed as part of the Django migration flow so that new databases bootstrap correctly.
   - **Acceptance Criteria**:
     - IF the deploying database role has superuser privileges THEN `python manage.py migrate` SHALL install the PostGIS extension.
     - IF the deploying role does NOT have superuser THEN the extension MUST be created out-of-band by a superuser before running migrations (documented caveat — see `.claude/guidelines.md`).

11.2 **User Story**: As a maintainer, I want CI to run the test suite on every push so that regressions are caught early.
   - **Acceptance Criteria**: `.github/workflows/ci.yml` SHALL configure a Python 3.12 + PostgreSQL/PostGIS test environment, run `ruff check .`, and run `manage.py test game --noinput` with `coverage --fail-under=80` on every push and PR.

### 12. Deployment Automation (Phase 1)

12.1 **User Story**: As a maintainer, I want every push to `main` to deploy to production so that releases are fast and repeatable.
   - **Acceptance Criteria**:
     - A GitHub Actions workflow SHALL trigger on push to `main` and deploy to the VPS at `cercetador.albascout.ro`.
     - The workflow SHALL SSH to the server, pull the latest code, install dependencies, run migrations, collect static files, and reload the gunicorn systemd unit.
     - The workflow SHALL run `curl -f https://cercetador.albascout.ro/health/` after reload and fail the deployment if the health check does not return 200.
     - Secrets SHALL be stored in GitHub repository secrets: `SSH_HOST`, `SSH_USER`, `SSH_KEY`, `DEPLOY_PATH`.
     - There is no staging environment; rollback is a manual `git reset --hard <prev>` + workflow re-run.

12.2 **User Story**: As a developer, I want CI to run the test suite and coverage check on every push so that broken code does not reach `main`.
   - **Acceptance Criteria**:
     - A GitHub Actions workflow SHALL run `python manage.py test` with a PostgreSQL+PostGIS service container on every pull request and push to any branch.
     - The workflow SHALL fail if branch coverage drops below 80%.
     - The workflow SHALL fail if `ruff check` finds violations.
     - Travis CI (`.travis.yml`) SHALL be removed once GHA CI is green.

12.3 **User Story**: As a maintainer, I want a health check endpoint so that deployment and uptime monitors can verify the service is live.
   - **Acceptance Criteria**:
     - `GET /health/` SHALL return HTTP 200 with a JSON body `{"status": "ok"}` when the app can reach the database.
     - It SHALL return HTTP 503 when the database is unreachable.
     - The endpoint SHALL not require authentication.

### 13. User Accounts (Phase 2)

13.1 **User Story**: As a scout, I want a personal account so that my submissions and team membership are tied to me, not to a shared team code.
   - **Acceptance Criteria**:
     - The system SHALL support per-person accounts built on Django's `User` model with a `UserProfile` 1:1 extension.
     - A user SHALL be able to register (email + password), log in, log out, and reset their password via email.
     - Authentication SHALL use DRF Token authentication, issued at login and invalidated at logout.
     - A user SHALL belong to at most one team at a time (many-to-many model internally for history, but only one active `TeamMembership` per (user, game) pair — see §18).

13.2 **User Story**: As an authenticated scout, I want all my challenge submissions attributed to my account so that my individual contribution is visible.
   - **Acceptance Criteria**:
     - `POST /api/team_tower_challenges/` SHALL require authentication and SHALL derive the submitting team from the authenticated user's active membership.
     - The `team_code` field and submission path SHALL be retired at Phase 2 launch (hard cutover). All existing team codes SHALL become inert.
     - The `TeamTowerChallenge` model SHALL gain a `submitted_by = ForeignKey(User)` field.

13.3 **User Story**: As a user, I want a "me" endpoint so that the frontend can render personalized state.
   - **Acceptance Criteria**: `GET /api/me/` SHALL return the current user's profile, active team membership, active game selection (see §18), and permissions.

### 14. Team Invites (Phase 2)

14.1 **User Story**: As a staff member, I want to invite scouts to a team by email or QR code so that team rosters are staff-controlled.
   - **Acceptance Criteria**:
     - Team creation SHALL be restricted to staff users.
     - Staff SHALL create invites via `POST /api/invites/` specifying team, email (optional — blank for QR-only invites), and expiration.
     - The system SHALL generate a single-use cryptographically random token for each invite.
     - IF email is provided THEN the system SHALL send an invite email containing `https://host/invite/{token}`.
     - A QR code image of the invite URL SHALL be available in the staff UI for in-person invites.

14.2 **User Story**: As an invitee, I want to accept an invite and either register a new account or join with an existing one.
   - **Acceptance Criteria**:
     - `GET /api/invites/{token}/` (unauthenticated) SHALL return the invite's team name, TeamGroup name, and expiration for preview rendering.
     - `POST /api/invites/accept/{token}/` SHALL:
       - Require either a logged-in user OR signup fields (email, password, first/last name).
       - Create a new `TeamMembership` linking the user to the invited team.
       - Mark the invite as accepted (`accepted_by`, `accepted_at`); subsequent accept attempts SHALL return 410 Gone.
       - Return an auth token for the logged-in user.
     - Expired invites SHALL return 410 Gone with a clear error.

14.3 **User Story**: As a staff member, I want to manage pending invites so that I can resend or revoke them.
   - **Acceptance Criteria**:
     - `GET /api/invites/` SHALL list invites for teams the staff member can manage, filterable by status (pending, accepted, expired, revoked).
     - `DELETE /api/invites/{id}/` SHALL revoke a pending invite (subsequent accept attempts return 410).
     - `POST /api/invites/{id}/resend/` SHALL re-send the invite email (does not rotate the token).

### 15. Angular Player App (Phase 2)

15.1 **User Story**: As a player, I want the existing game experience delivered via a modern Angular SPA so that the UI is fast and mobile-friendly.
   - **Acceptance Criteria**:
     - An Angular v21 project `frontend/projects/player` SHALL replicate all player-facing functionality currently in Django templates (main map, per-TeamGroup score maps, tower detail, challenge submission, RFID capture, rules).
     - The app SHALL use standalone components, signals, the new `@if`/`@for` control flow, `input()`/`output()`/`inject()`, and `ChangeDetectionStrategy.OnPush`.
     - The app SHALL consume the DRF API; Django templates for these routes SHALL be removed at Phase 2 launch.
     - The map SHALL use Leaflet with live updates (polling or refresh button — no websockets required in Phase 2).
     - Photo upload for challenge submission SHALL use the browser camera via the `<input type="file" capture="environment">` pattern.

15.2 **User Story**: As a player using the app, I want GPS proximity feedback before submitting so that I don't waste submissions.
   - **Acceptance Criteria**: The tower detail page SHALL show live distance-to-tower from the device GPS and SHALL disable the submit button when the player is more than 50 meters away.

15.3 **User Story**: As a player, I want clear cooloff feedback after a rejection so that I know when I can retry.
   - **Acceptance Criteria**: After a rejected attempt, the tower page SHALL show a countdown until the 5-minute cooloff expires.

### 16. Angular Staff App (Phase 2)

16.1 **User Story**: As a staff member, I want an Angular staff UI for the most common operational tasks so that I don't have to open Django admin for routine work.
   - **Acceptance Criteria**:
     - An Angular project `frontend/projects/staff` SHALL provide: pending review queue, tower/zone/team CRUD, challenge management, invite management, live scoreboard, and game state panel.
     - The staff UI SHALL NOT replace Django admin for rare operations; a "Django Admin" link SHALL be visible in the staff UI.
     - Staff access SHALL be gated behind `is_staff=True` on the user.

16.2 **User Story**: As a reviewer, I want a pending queue optimized for fast confirm/reject decisions.
   - **Acceptance Criteria**:
     - The queue SHALL list oldest-first and show photo, submitter, team, tower, challenge text, and submission timestamp at a glance.
     - Confirm and Reject SHALL be one-click actions with optional `response_text` modal for Reject.

16.3 **User Story**: As a staff member, I want a live scoreboard that updates as captures happen.
   - **Acceptance Criteria**:
     - The scoreboard SHALL show each team's locked + floating score with per-TeamGroup tabs.
     - The scoreboard SHALL refresh automatically (polling every 30s is acceptable; websockets not required in Phase 2).

### 17. Game Entity (partially implemented, Phase 3 will complete)

17.1 **User Story**: As an administrator, I want a `Game` entity that owns zones, towers, teams, and team groups so that multiple independent games can run on one server.
   - **Status**: Partially implemented in the pre-Phase-0 refactor. `organize.Game`, `organize.TeamGroup`, `organize.Team` exist; `game.Zone`, `game.Tower`, `game.Team` carry a mandatory `game = ForeignKey(Game)` FK. `Challenge` does NOT yet have a `game` FK — Phase 3 will add this.
   - **Acceptance Criteria (target end of Phase 3)**:
     - `Game` SHALL have: `name`, `players` M2M, `base_point` + `base_zoom_level` (map defaults), `start_time`, `end_time`, `is_active`. Additional configurable rule fields (`proximity_meters` default 50, `cooloff_minutes` default 5, `initial_bonus_default` default 0) SHALL be added in Phase 3.
     - `Zone`, `Tower`, `Team` ALREADY have a mandatory `game` FK.
     - `Challenge` SHALL gain a `game` FK (Phase 3).
     - `TeamTowerChallenge` SHALL gain a denormalized `game_id` for query performance (Phase 3).
     - All queries SHALL be scoped by game; a reusable `GameScopedViewSet` / queryset mixin SHALL enforce this at the API layer (Phase 3).

17.2 **User Story**: As a staff member, I want to configure per-game rules so that different events can have different behavior.
   - **Status**: Not yet implemented. Proximity (50m) and cooloff (5min) are still hardcoded in `game.views` and `game.forms` / `game.models.Tower.team_in_cooloff`.
   - **Acceptance Criteria**:
     - Proximity threshold (`proximity_meters`) SHALL be read from the game config, not hardcoded.
     - Cooloff duration (`cooloff_minutes`) SHALL be read from the game config.
     - Existing hardcoded 50m and 5min values SHALL remain the defaults for the Default Game so existing tests continue to pass.

### 18. Multi-Game Operation (Phase 3)

18.1 **User Story**: As a user, I want to select which game I'm currently playing or administering so that I see only that game's state.
   - **Acceptance Criteria**:
     - `UserProfile` SHALL have a `current_game = ForeignKey(Game, null=True)` field.
     - `GET/POST /api/current-game/` SHALL read and write the current game selection.
     - For players, selection SHALL default to the game of their active team membership; cross-game team membership is not supported in Phase 3.
     - For staff, the UI SHALL show a game switcher; all staff views SHALL filter by the selected game.

18.2 **User Story**: As a staff member, I want to create, edit, activate, and deactivate games so that I can run events independently.
   - **Acceptance Criteria**:
     - `POST /api/games/` (staff-only) SHALL create a game.
     - `PATCH /api/games/{id}/` SHALL edit name, slug, rules, dates, and active flag.
     - Deactivating a game (`is_active=False`) SHALL hide it from player views but SHALL NOT close ownerships (historical record preserved).

18.3 **User Story**: As a player, I want to only see the towers, zones, and teams of my game.
   - **Acceptance Criteria**: The main map, score maps, and all API reads SHALL filter by the viewer's current game.

### 19. Game Cloning (Phase 3)

19.1 **User Story**: As a staff member organizing a new event, I want to clone an existing game's zones, towers, and challenges so that I don't have to recreate map data.
   - **Acceptance Criteria**:
     - A `clone_game` management command SHALL take a source game slug and a target game name/slug and deep-copy all Zones, Towers, and Challenges into a new Game.
     - Teams SHALL NOT be copied by default (fresh roster per event); a `--include-teams` flag SHALL opt-in to copy team rows (without memberships).
     - A staff UI "Clone game" action SHALL wrap the management command.
     - `TeamTowerChallenge`, `TeamTowerOwnership`, and `TeamZoneOwnership` records SHALL NOT be cloned — the new game starts with a clean slate.

## Open Items (future consideration)

Tracked from repo `TODO.md`, still awaiting detailed specifications:
- **TODO-A**: When the "day" ends (event daily cut-off) pause / close all active `TeamTowerOwnership` records.
- **TODO-B**: When the day resumes, reopen ownerships.
- **TODO-C**: Define explicit consequences when a team fails a challenge beyond the 5-minute cooloff (e.g., progression rollback, alternative penalties). Current behavior is only the cooloff.
