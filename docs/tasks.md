# Technical Task List

Tasks are linked to [plan.md](plan.md) items and [requirements.md](requirements.md) items using the format `(Plan: X, Req: Y)`. Mark completion by changing `[ ]` to `[x]`. Work already shipped on `main` is pre-checked based on code inspection.

## Phase 1: Core Models & Admin
- [x] T1.1: Define `Zone` model with `PolygonField`, color, and `score_type` choices. (Plan: I1, Req: 1.1)
- [x] T1.2: Define `Tower` model with `PointField`, category (NORMAL/RFID), `is_active`, `rfid_code`, `zone` FK. (Plan: I1, TW1, Req: 1.2)
- [x] T1.3: Define `Team` model with category choices, unique `team_code`, color, description. (Plan: T1, Req: 2.1)
- [x] T1.4: Define `Challenge` model with difficulty and optional tower binding. (Plan: C1, Req: 3.1)
- [x] T1.5: Define `TeamTowerChallenge`, `TeamTowerOwnership`, `TeamZoneOwnership` records. (Plan: CS1, SC1, SC3, Req: 4.1, 6.1, 6.3)
- [x] T1.6: Configure Django admin for all models with filters, color display, and ownership columns. (Plan: I2, Req: 9.1)
- [x] T1.7: Add readonly `floating_score` column to Team admin. (Plan: SC1, Req: 9.1)
- [x] T1.8: Add attempt/success counts to Challenge admin. (Plan: C3, Req: 9.1)

## Phase 2: Scoring & Game Mechanics
- [x] T2.1: Implement four zone `score_type` functions (LINEAR, LOGARITHMIC, EXPONENTIAL, BONUS). (Plan: SC2, Req: 6.2)
- [x] T2.2: Implement `Team.current_score()` = locked score + floating score. (Plan: SC1, Req: 6.1)
- [x] T2.3: Implement `Tower.assign_to_team()` closing prior ownership, opening new one, awarding `initial_bonus`. (Plan: CS5, Req: 4.4, 6.4)
- [x] T2.4: Implement majority-rule zone recalculation on tower ownership change. (Plan: SC3, Req: 6.3)
- [x] T2.5: Add `Tower.initial_bonus` field and capture-time bonus logic. (Plan: SC4, Req: 6.4) *(commits 17aeb8f, e028d5f)*
- [x] T2.6: Implement next-challenge selection (tower-specific-first, then generic by difficulty, hardest-generic fallback). (Plan: C2, Req: 3.2)
- [x] T2.7: Unit tests for scoring and next-challenge logic in `game/tests.py`. (Plan: C2, SC1, Req: 3.2, 6.1)

## Phase 3: Submission & Review Flow
- [x] T3.1: Build challenge submission form + view with 50m proximity check. (Plan: CS1, CS2, V4, Req: 4.1)
- [x] T3.2: Implement 5-minute cooldown after a REJECTED attempt. (Plan: CS4, Req: 4.3)
- [x] T3.3: Admin-based confirm/reject with `checked_by`, `verified_at`, `response_text`, `time_diff`. (Plan: CS3, Req: 4.2)
- [x] T3.4: Auto-capture on CONFIRMED: call `tower.assign_to_team()`. (Plan: CS5, Req: 4.4)
- [x] T3.5: `/pending/` page showing pending challenge count. (Plan: CS6, Req: 4.2)
- [x] T3.6: Support photo upload in `TeamTowerChallenge`. (Plan: CS1, Req: 4.1) *(migration 0011)*

## Phase 4: Player Views & Map
- [x] T4.1: `/` main Leaflet map showing zones + active towers with per-category team colors. (Plan: V1, Req: 1.3)
- [x] T4.2: Category-specific score maps `/explo/`, `/temerari/`, `/seniori/`. (Plan: V2, Req: 7.2)
- [x] T4.3: `/tower/<id>/` tower detail with team-code entry, next challenge, cooldown indicator. (Plan: V3, Req: 7.1)
- [x] T4.4: `/rules/` static rules page. (Plan: V6)

## Phase 5: RFID Tower Capture
- [x] T5.1: Add `rfid_code` field to Tower. (Plan: TW3, Req: 1.2) *(migration 0008)*
- [x] T5.2: `/tower/rfid/<rfid_code>/` resolves to matching tower and renders RFID capture page. (Plan: V5, TW3, Req: 5.1)
- [x] T5.3: RFID capture auto-confirms (outcome=CONFIRMED) and still enforces 50m proximity. (Plan: CS2, TW3, Req: 5.1)
- [x] T5.4: Tower admin shows a clickable public RFID URL for RFID-category towers. (Plan: I2, Req: 5.2, 9.1)

## Phase 6: REST API
- [x] T6.1: `GET /api/zones/` GeoJSON viewset via `rest_framework_gis`. (Plan: API1, Req: 8.1)
- [x] T6.2: `GET /api/towers/` GeoJSON with `lat`/`lng`/`accuracy` proximity filtering. (Plan: API2, Req: 8.1)
- [x] T6.3: `GET /api/teams/` with django-filter by category. (Plan: API3, Req: 8.1)
- [x] T6.4: `GET /api/challenges/` including generic challenges. (Plan: API4, Req: 8.1)
- [x] T6.5: `POST /api/team_tower_challenges/` with photo upload and proximity check. (Plan: API5, Req: 4.1, 8.1)

## Phase 7: Game State & Admin Actions
- [x] T7.1: Tower admin `unassign_all` action that closes all active tower/zone ownerships. (Plan: TW2, Req: 7.3)
- [x] T7.2: Deactivating a tower closes its ownerships and triggers zone recomputation. (Plan: TW2, Req: 7.3)

## Phase 8: Data Import
- [x] T8.1: `import_data` management command parses `zone_normal.kml`, `zone_bonus.kml`, `puncte.kml`. (Plan: IMP1, Req: 10.1)

## Phase 9: Deployment
- [x] T9.1: `.travis.yml` configured with PostgreSQL service, runs `manage.py test --noinput`. (Plan: I4, Req: 11.2)
- [x] T9.2: PostGIS extension supported via Django migration (commented-out `CreateExtension`, requires DB superuser). (Plan: I3, Req: 11.1) *(commits 51c43e8, e61acc3)*

## Phase 0: Python/Django Upgrade + Aspirational Test Suite
- [x] T0.1: Bump Django 3.1 → 5.x and Python 3.11 → 3.12; fix removed APIs (`url()`, `USE_L10N`, `ugettext_*`, `default_app_config`). (Plan: P0.1)
- [x] T0.2: Upgrade DRF, rest_framework_gis, django-leaflet, django-colorfield, django-filter, Pillow to latest; swap psycopg2 → psycopg[binary] v3. (Plan: P0.2)
- [x] T0.3: Split requirements.txt into runtime + requirements-dev.txt. (Plan: P0.3)
- [x] T0.4: Write test suite: scoring (4 score_types + current_score). (Plan: P0.4, Req: 6.1, 6.2)
- [x] T0.5: Write test suite: tower capture (initial_bonus awarded, prior ownership closed, new ownership opened). (Plan: P0.4, Req: 4.4, 6.4)
- [x] T0.6: Write test suite: majority zone recalculation on capture / deactivation / unassign_all. (Plan: P0.4, Req: 6.3, 7.3)
- [x] T0.7: Write test suite: 50m proximity check (form + API). (Plan: P0.4, Req: 4.1, 8.1)
- [x] T0.8: Write test suite: 5-minute cooloff (rejected → cannot resubmit until expired). (Plan: P0.4, Req: 4.3)
- [x] T0.9: Write test suite: next-challenge selection (tower-specific-first, generic by difficulty, hardest-generic fallback). (Plan: P0.4, Req: 3.2)
- [x] T0.10: Write test suite: RFID auto-confirm + proximity. (Plan: P0.4, Req: 5.1)
- [x] T0.11: Write test suite: API endpoints — zones, towers (with lat/lng/accuracy), teams (category filter), challenges, challenge submission. (Plan: P0.4, Req: 8.1)
- [x] T0.12: Write test suite: admin `unassign_all` action. (Plan: P0.4, Req: 7.3)
- [x] T0.13: Replace Travis CI with GitHub Actions (test + coverage gate ≥80% + ruff). (Plan: P0.5, Req: 12.2)
- [x] T0.14: Add `GET /health/` endpoint with DB reachability check. (Plan: P0.6, Req: 12.3)

## Phase 1: GHA Deploy to VPS
- [x] T1.1: Create `.github/workflows/deploy.yml` SSH-to-VPS deploy workflow (pull, install, migrate, collectstatic, reload gunicorn, curl /health/). (Plan: P1.1, Req: 12.1)
- [x] T1.2: Write `docs/deployment.md` with gunicorn supervisord unit, nginx config template, PostgreSQL+PostGIS provisioning, Let's Encrypt setup. (Plan: P1.2, Req: 12.1)
- [x] T1.3: Wire `/health/` through nginx proxy; verify accessible from public domain. (Plan: P1.3, Req: 12.1, 12.3)

## Phase 2A: DRF API Expansion
- [ ] T2A.1: Enable DRF token authentication; add `POST /api/auth/login`, `logout`, `register`, `password-reset`. (Plan: P2A.1, Req: 13.1)
- [ ] T2A.2: Add `GET /api/me/`, `PATCH /api/me/`, `GET /api/my-team/`. (Plan: P2A.2, Req: 13.3)
- [ ] T2A.3: Implement Invites API: `GET/POST/DELETE /api/invites/`, unauth preview, accept, resend. (Plan: P2A.3, Req: 14.1, 14.2, 14.3)
- [ ] T2A.4: Refactor `POST /api/team_tower_challenges/` to require auth, derive team from user, add `submitted_by` FK. (Plan: P2A.4, Req: 13.2)
- [ ] T2A.5: Add `GET/POST /api/current-game/` endpoint (stubbed against a default game; fully wired in Phase 3). (Plan: P2A.5, Req: 13.3, 18.1)

## Phase 2B: Angular Scaffold
- [ ] T2B.1: Initialize Angular v21 workspace at `frontend/` with `player`, `staff`, and `shared` projects. (Plan: P2B.1, Req: 15.1, 16.1)
- [ ] T2B.2: Add `.mcp.json` with `angular-cli` MCP server; document usage in `.claude/guidelines.md`. (Plan: P2B.2)
- [ ] T2B.3: Configure dev proxy (`/api/`, `/admin/` → `:8000`) and production build output paths. (Plan: P2B.3, Req: 15.1)

## Phase 2C: Player UI
- [ ] T2C.1: Login, register, password-reset, and invite-accept landing screens. (Plan: P2C.1, Req: 13.1, 14.2)
- [ ] T2C.2: Main Leaflet map view with zones + active towers, category-colored. (Plan: P2C.2, Req: 15.1)
- [ ] T2C.3: Tower detail page with live GPS distance, cooloff countdown, challenge submit form with photo capture. (Plan: P2C.3, Req: 15.1, 15.2, 15.3)
- [ ] T2C.4: Per-TeamGroup score map view at `/map/<slug>/` (dynamic on TeamGroup.slug). (Plan: P2C.4, Req: 15.1)
- [ ] T2C.5: Rules page. (Plan: P2C.5)

## Phase 2D: Accounts & Invites Backend
- [ ] T2D.1: Add `UserProfile`, `TeamMembership`, `Invite` models with migrations. (Plan: P2D.1, Req: 13.1, 14.1)
- [ ] T2D.2: Email templates (HTML + text) for invite emails. (Plan: P2D.2, Req: 14.1)
- [ ] T2D.3: QR code rendering component for invite tokens in staff UI. (Plan: P2D.3, Req: 14.1)
- [ ] T2D.4: Remove `team_code`-based submission flow; mark `Team.team_code` deprecated (drop in Phase 3). (Plan: P2D.4, Req: 13.2)

## Phase 2E: Staff UI
- [ ] T2E.1: Pending review queue with photo preview + one-click confirm/reject. (Plan: P2E.1, Req: 16.2)
- [ ] T2E.2: Tower/Zone/Team CRUD with activate/deactivate toggles and `unassign_all`. (Plan: P2E.2, Req: 16.1)
- [ ] T2E.3: Challenge management (list + create/edit; tower-specific or generic). (Plan: P2E.3, Req: 16.1)
- [ ] T2E.4: Invite management UI (list, create, revoke, resend). (Plan: P2E.4, Req: 14.3)
- [ ] T2E.5: Live scoreboard (per-category tabs, 30s polling). (Plan: P2E.5, Req: 16.3)
- [ ] T2E.6: Game state panel (end-game, reset). (Plan: P2E.6, Req: 16.1)

## Phase 2F: Template Removal
- [ ] T2F.1: Delete `game/templates/` and associated template views; keep admin templates. Wire root URL to Angular build. (Plan: P2F.1, Req: 15.1)

## Phase 2G: E2E Tests
- [ ] T2G.1: Install and configure Playwright in `frontend/`. (Plan: P2G.1)
- [ ] T2G.2: Player journey E2E: invite → register → login → map → submit challenge with photo. (Plan: P2G.2, Req: 13.1, 14.2, 15.1)
- [ ] T2G.3: Staff journey E2E: create invite → review submission → confirm → tower color updates. (Plan: P2G.3, Req: 16.1, 16.2)

## Phase 3: Multi-Game Support
- [ ] T3.1: Add `Game` model with config fields; add `game` FK to Zone/Tower/Team/Challenge; data migration creates Default Game and backfills. (Plan: P3.1, Req: 17.1)
- [ ] T3.2: Implement `GameScopedViewSet` mixin; update all viewsets to scope by current game. (Plan: P3.2, Req: 17.1, 18.3)
- [ ] T3.3: Replace hardcoded 50m and 5min constants with Game config reads. (Plan: P3.3, Req: 17.2)
- [ ] T3.4: Add Games CRUD API (`GET/POST/PATCH/DELETE /api/games/`). (Plan: P3.4, Req: 18.2)
- [ ] T3.5: Add current-game selector UI in staff app; default players to their team's game. (Plan: P3.5, Req: 18.1)
- [ ] T3.6: Implement `clone_game` management command (deep-copy Zones/Towers/Challenges; `--include-teams` opt-in). (Plan: P3.6, Req: 19.1)
- [ ] T3.7: Add "Clone game" button to staff UI wrapping the command. (Plan: P3.7, Req: 19.1)
- [ ] T3.8: Drop `Team.team_code` column (Phase 2 hard cutover complete). (Plan: P3.8, Req: 13.2)

## Phase 10: Open Items (from TODO.md — specs needed first)
- [ ] T10.1: Specify and implement day-cutoff pausing of TeamTowerOwnership. (Plan: OPEN1) — **blocked on requirements definition**
- [ ] T10.2: Specify and implement day-start resumption of TeamTowerOwnership. (Plan: OPEN1) — **blocked on requirements definition**
- [ ] T10.3: Specify and implement challenge-failure consequences beyond 5-min cooloff. (Plan: OPEN2) — **blocked on requirements definition**

## Adding New Tasks

When adding new features or bug fixes:
1. Check whether the feature already appears in [requirements.md](requirements.md). If not, ADD a numbered requirement first (with a user story and SHALL acceptance criteria).
2. Add a corresponding plan item in [plan.md](plan.md) linking back to the requirement.
3. Add one or more tasks here using: `- [ ] TX.Y: Description. (Plan: Z, Req: W)`.
4. Mark `[x]` when done.
