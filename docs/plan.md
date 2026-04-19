# Implementation Plan

This plan maps existing functionality (and open items) for the geogame project to the requirements in [requirements.md](requirements.md). The project is split across three Python packages:

- `geogame/` — project module (settings, urls, wsgi)
- `game/` — app owning `Zone`, `Tower`, `Challenge`, `TeamTowerChallenge`, ownership records
- `organize/` — app owning `Game`, `TeamGroup`, `Team`, `Player`, `TeamPlayer`

Use this doc as the index from requirements → modules/code.

## Core Infrastructure
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **I1. Geospatial Models** | `game.Zone` (PolygonField) and `game.Tower` (PointField) using `django.contrib.gis`. | 1.1, 1.2 | High |
| **I2. Admin Interface** | Rich Django Admin for Zone, Tower, Team, TeamGroup, Challenge, TeamTowerChallenge with color, filters, counts, and readonly scoring fields. smart-selects chained dropdowns on Team.group (chained by Team.game). | 9.1 | High |
| **I3. PostGIS Bootstrapping** | Migration installs `postgis` extension (commented-out `CreateExtension` — relies on DB superuser or pre-provisioned extension). | 11.1 | High |
| **I4. CI** | GitHub Actions (`.github/workflows/ci.yml`) runs ruff + Django test suite with PostGIS service + coverage gate (≥80%). | 11.2 | Medium |

## Teams & TeamGroups
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **T1. Team & Group Models** | `organize.Team` with unique `code`, color, description, `game` FK, optional `group` FK (TeamGroup, chained by game). `organize.TeamGroup(name, slug, game)` unique per (game, slug). | 2.1 | High |
| **T2. Per-TeamGroup Scoring** | All ownership and leaderboard computations partition by TeamGroup. | 2.2 | High |

## Tower System
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **TW1. Tower Model** | `Tower` with category (NORMAL/RFID), optional `zone`, `is_active`, `initial_bonus`, `rfid_code`. | 1.2 | High |
| **TW2. Tower Deactivation** | Setting `is_active=False` (or running admin `unassign_all`) closes active TeamTowerOwnership/TeamZoneOwnership records. | 7.3 | High |
| **TW3. RFID Route** | `/tower/rfid/<rfid_code>/` resolves to matching tower, auto-confirms capture on scan + proximity check. | 5.1, 5.2 | Medium |

## Challenge System
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **C1. Challenge Model** | `Challenge` with difficulty, optional tower binding (generic when unset), text content. | 3.1 | High |
| **C2. Next-Challenge Logic** | Selects lowest-difficulty tower-specific challenge first, then generic by difficulty, with hardest-generic fallback. Tested in `game/tests.py`. | 3.2 | High |
| **C3. Challenge Admin Stats** | List view shows attempt counts and confirmed counts per challenge. | 9.1 | Low |

## Challenge Submission & Review
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **CS1. Submission Flow** | `TeamTowerChallenge` created with outcome=`PENDING`; stores photo, submitter, location, team, tower, challenge. | 4.1 | High |
| **CS2. 50m Proximity Check** | Rejects submissions if GPS location is > 50m from tower. Applies to both web form and API. | 4.1, 5.1 | High |
| **CS3. Staff Review** | Admin-based confirm/reject with `checked_by`, `verified_at`, `response_text`, `time_diff` readonly. | 4.2 | High |
| **CS4. 5-Minute Cooldown** | After `REJECTED`, team cannot resubmit on the same tower for 5 minutes. | 4.3 | Medium |
| **CS5. Auto-Capture on Confirm** | Confirming a challenge calls `tower.assign_to_team(team)` which awards `initial_bonus`, opens TeamTowerOwnership, triggers zone recalculation. | 4.4, 6.3, 6.4 | High |
| **CS6. Pending Queue** | `/pending/` page surfaces pending count for staff. | 4.2 | Low |

## Scoring System
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **SC1. Locked + Floating Score** | `Team.score` (locked, cumulative) + `floating_score` (computed from open TeamZoneOwnerships). `current_score()` sums both. | 6.1 | High |
| **SC2. Zone Score Functions** | Four strategies: `LINEAR`, `LOGARITHMIC`, `EXPONENTIAL`, `BONUS` (exponential capped at 200). | 6.2 | High |
| **SC3. Majority Zone Control** | Recompute zone owner on every tower ownership change: strict majority of active towers in the zone (per category). | 6.3 | High |
| **SC4. Initial Bonus on Capture** | Capturing a tower adds `tower.initial_bonus` to locked score. Covered by dedicated tests (`tests.py`). | 6.4 | High |

## Player Views (Templates)
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **V1. Main Map** | `/` renders zones + active towers via Leaflet, colored by current per-category controllers. | 1.3 | High |
| **V2. Category Score Maps** | `/explo/`, `/temerari/`, `/seniori/` — category-scoped score maps. | 7.2 | Medium |
| **V3. Tower Detail** | `/tower/<id>/` — team-code-gated page showing next challenge, ownership state, cooldown status. | 7.1 | High |
| **V4. Challenge Form** | `/tower/challenge/` — form POST for challenge submission. | 4.1 | High |
| **V5. RFID Tower Page** | `/tower/rfid/<rfid_code>/` — instant-capture page for RFID scans. | 5.1 | Medium |
| **V6. Rules Page** | `/rules/` static rules page. | - | Low |

## REST API
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **API1. Zones** | GeoJSON read-only `GET /api/zones/` via `rest_framework_gis`. | 8.1 | High |
| **API2. Towers** | GeoJSON read-only `GET /api/towers/` with `lat`/`lng`/`accuracy` filtering; returns only active towers. | 8.1 | High |
| **API3. Teams** | `GET /api/teams/`, filterable by category (django-filter). | 8.1 | Medium |
| **API4. Challenges** | `GET /api/challenges/` — full list including generic. | 8.1 | Medium |
| **API5. Challenge Submission** | `POST /api/team_tower_challenges/` — photo upload, proximity check, returns pending record. | 4.1, 8.1 | High |

## Data Import
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **IMP1. KML Import** | `manage.py import_data` parses `zone_normal.kml`, `zone_bonus.kml`, `puncte.kml` → bulk seed Zones/Towers (delete-and-recreate). | 10.1 | Medium |

## Phase 0 — Python/Django Upgrade + Aspirational Test Suite
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P0.1 Django 5 Upgrade** | Bump Django 3.1 → 5.x, Python 3.11 → 3.12. Fix removed APIs (`url()`, `USE_L10N`, `ugettext_*`, `default_app_config`). | - | High |
| **P0.2 Deps Refresh** | DRF, rest_framework_gis, django-leaflet, django-colorfield, django-filter, Pillow all to latest. `psycopg2` → `psycopg[binary]` v3. | - | High |
| **P0.3 Requirements Split** | Split `requirements.txt` into runtime + `requirements-dev.txt` (ipython, pytest, coverage, ruff). | - | Medium |
| **P0.4 Test Suite** | Aspirational ≥80% branch coverage: scoring (all 4 functions + current_score), capture flow, cooloff, next-challenge, RFID auto-confirm, proximity check, all API endpoints, admin `unassign_all`. | 12.2 | High |
| **P0.5 GHA CI** | Replace Travis with GitHub Actions: test + coverage + ruff on every PR and push. | 12.2 | High |
| **P0.6 Health Endpoint** | Add `GET /health/` returning 200/503 based on DB reachability. | 12.3 | High |

## Phase 1 — GHA Deploy to VPS
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P1.1 Deploy Workflow** | `.github/workflows/deploy.yml`: SSH to VPS, pull, install, migrate, collectstatic, reload gunicorn, curl `/health/`. | 12.1 | High |
| **P1.2 Server Setup Docs** | `docs/deployment.md`: gunicorn systemd unit, nginx config template, PostgreSQL+PostGIS provisioning steps, Let's Encrypt setup. | 12.1 | Medium |
| **P1.3 Health Wiring** | Ensure `/health/` is reachable from the public domain (nginx proxy). | 12.1, 12.3 | Medium |

## Phase 2A — DRF API Expansion
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2A.1 Token Auth** | Enable DRF token auth; `POST /api/auth/login`, `logout`, `register`, `password-reset`. | 13.1 | High |
| **P2A.2 User/Me Endpoint** | `GET /api/me/`, `GET /api/my-team/`, `PATCH /api/me/`. | 13.3 | High |
| **P2A.3 Invites API** | `GET/POST/DELETE /api/invites/`, `GET /api/invites/{token}/` (unauth preview), `POST /api/invites/accept/{token}/`, `POST /api/invites/{id}/resend/`. | 14.1, 14.2, 14.3 | High |
| **P2A.4 Auth Refactor for Submissions** | `POST /api/team_tower_challenges/` requires auth; retire `team_code` path; add `submitted_by` FK. | 13.2 | High |
| **P2A.5 Current-Game Endpoint** | `GET/POST /api/current-game/` (stub in Phase 2 using a default game; wired fully in Phase 3). | 13.3, 18.1 | Medium |

## Phase 2B — Angular Scaffold
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2B.1 Angular Workspace** | `frontend/` Angular v21 workspace with `player` and `staff` projects + `shared` lib. | 15.1, 16.1 | High |
| **P2B.2 MCP Setup** | `.mcp.json` with `angular-cli` MCP server; document usage in `.claude/guidelines.md`. | - | Medium |
| **P2B.3 Proxy & Build Config** | Proxy `/api/` and `/admin/` to Django at `:8000` in dev; production build collected into Django `STATIC_ROOT` or served by nginx directly. | 15.1 | High |

## Phase 2C — Player UI
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2C.1 Auth Screens** | Login, register, password reset, invite-accept landing. | 13.1, 14.2 | High |
| **P2C.2 Map View** | Main Leaflet map with zones + active towers, category-colored. | 15.1 | High |
| **P2C.3 Tower Detail** | Current challenge, proximity indicator, cooloff countdown, submit form with photo capture. | 15.1, 15.2, 15.3 | High |
| **P2C.4 TeamGroup Score Views** | Per-TeamGroup score map at `/map/<slug>/` (one view, dynamic on the group's slug). | 15.1 | Medium |
| **P2C.5 Rules Page** | Static rules page. | 15.1 | Low |

## Phase 2D — Accounts & Invites
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2D.1 Account Models** | `UserProfile` (1:1 with User), `TeamMembership` (user ↔ team, active flag), `Invite` (token, team, email, expires_at, accepted_by, accepted_at, revoked). | 13.1, 14.1 | High |
| **P2D.2 Invite Email Templates** | Branded HTML + text email for invites with URL + fallback instructions. | 14.1 | Medium |
| **P2D.3 Invite QR Rendering** | Staff UI renders invite token as QR (Angular `ngx-qrcode` or equivalent). | 14.1 | Medium |
| **P2D.4 team_code Retirement** | Remove `team_code`-based submission path; mark field deprecated; drop in Phase 3. Hard cutover at Phase 2 launch. | 13.2 | High |

## Phase 2E — Staff UI
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2E.1 Review Queue** | Pending-first list, photo preview, one-click confirm / reject-with-response. | 16.2 | High |
| **P2E.2 Tower/Zone/Team CRUD** | Forms and list views for Tower, Zone, Team. Includes activate/deactivate toggles and `unassign_all`. | 16.1 | High |
| **P2E.3 Challenge Management** | List + create/edit (tower-specific or generic). | 16.1 | Medium |
| **P2E.4 Invite Management** | List, create, revoke, resend invites. | 14.3 | High |
| **P2E.5 Live Scoreboard** | Per-category scoreboard with 30s polling refresh. | 16.3 | High |
| **P2E.6 Game State Panel** | End-game (`unassign_all`), reset controls. | 16.1 | Medium |

## Phase 2F — Template Removal
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2F.1 Remove Django Templates** | Delete `game/templates/` and associated template views. Keep admin templates. Angular handles all public routes. | 15.1 | High |

## Phase 2G — E2E Tests
| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P2G.1 Playwright Setup** | Install + configure Playwright in `frontend/`; run against local Django + Angular dev servers. | - | High |
| **P2G.2 Player Journey E2E** | Invite → register → login → view map → submit challenge with photo. | 13.1, 14.2, 15.1 | High |
| **P2G.3 Staff Journey E2E** | Create invite → review submission → confirm → tower color updates on map. | 16.1, 16.2 | High |

## Phase 3 — Session Model + Multi-Game Support

Phase 3 introduces `Session` as the runtime entity that sits between `Game`
(event config) and `Team` (roster / scoring state). Two parallel Sessions on
the same Game share the tower/zone/challenge configuration but keep separate
scoreboards. `clone_game` from earlier drafts disappears — creating a new
Session on an existing Game *is* the clone flow.

| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P3.1 Game Config Fields** | Add `slug` (unique), `proximity_meters`, `cooloff_minutes`, `initial_bonus_default`, `created_by`, `created_at` to `organize.Game`. Add `game` FK to `game.Challenge` with backfill from `tower.game`. | 17.1 | High |
| **P3.2 Session Model + Migration** | New `organize.Session(game, slug, name, start_time, end_time, is_active, created_by, created_at)`. Data migration: for each existing Game, create a default Session inheriting its dates/is_active; re-parent every Team from `game` FK to `session` FK; drop `Team.game`, `Game.start_time`, `Game.end_time`. `(game, slug)` unique. | 18.1 | High |
| **P3.3 Current-Session Profile + Endpoint** | Rename `UserProfile.current_game` → `current_session`. Replace `/api/current-game/` with `/api/current-session/` (returns session + nested game). | 18.2 | High |
| **P3.4 TeamMembership Uniqueness** | Denormalize `game` onto `TeamMembership` (sourced from `team.session.game`, kept in sync in `save()`). Add conditional unique constraint `(user, game)` where `is_active=True`. Invite-accept and admin flows SHALL surface a friendly error on conflict. | 18.3 | High |
| **P3.5 Scoping Mixins** | Introduce `SessionScopedViewSet` (Team, ownerships, submissions) and `GameScopedViewSet` (Zone, Tower, Challenge, TeamGroup). Apply to every existing viewset. | 17.1, 18.4 | High |
| **P3.6 Per-Game Config Reads** | Replace hardcoded 50m proximity and 5min cooloff with `session.game.proximity_meters` / `cooloff_minutes`. Update tower state endpoint, submission serializer, and the `team_in_cooloff` model method. | 17.2 | High |
| **P3.7 Games + Sessions CRUD API** | `GET/POST/PATCH/DELETE /api/staff/games/` and `/api/staff/sessions/`. Session deactivation SHALL close all open ownerships on that session (mirrors `unassign_all`). | 18.5 | High |
| **P3.8 Staff UI — Games, Sessions, Switcher** | Staff pages for Games list/edit and Sessions list/edit (grouped by Game). Current-session switcher in the navbar, grouped by Game. | 18.2, 18.5 | High |
| **P3.9 Player Default-Session Logic** | On login/profile fetch, if the player has exactly one active TeamMembership on an active Session, auto-select it; otherwise surface a "pick your session" picker. | 18.2 | Medium |
| **P3.10 Session History Views** | Staff: "Past sessions" list filterable by Game with a read-only final scoreboard + ownership timeline. Player: list of own past sessions with per-team read-only scoreboard. | 19.1, 19.2 | Medium |
| **P3.11 Drop legacy `team_code`** | Schema migration removing the Phase-2-deprecated `organize.Team.team_code` column. | 13.2 | Low |

## Phase 10 — Day Pausing + Failure Consequences

Staff-triggered Session pauses (events span multiple days) and configurable challenge-failure penalties. All behavior is opt-in — defaults preserve current Phase 3 behavior.

| Item | Description | Linked Requirements | Priority |
| :--- | :--- | :--- | :--- |
| **P10.1 PauseWindow Model + Pause/Resume API** | New `game.PauseWindow(session, started_at, ended_at, closed_tower_ownerships, closed_zone_ownerships)` + pause knobs on `Game` (with per-`Session` overrides). `POST /api/staff/sessions/{id}/pause/` + `/resume/` endpoints. On pause: close active `TeamTower`/`TeamZone`Ownership rows and record them on the window. On resume: reopen matching rows with `timestamp_start=now` when `pause_restores_ownerships_on_resume=True`. | 20.1, 20.2 | Medium |
| **P10.2 Pause-Aware Scoring + Submissions** | `Team.floating_score()` SHALL evaluate as of the open window's `started_at` when `pause_freezes_floating_score=True`. Submission serializer SHALL reject with HTTP 409 while paused when `pause_rejects_submissions=True`, else store `PENDING` without capture. `POST /api/staff/games/{id}/pause_all/` SHALL pause every active Session on the game. | 20.1, 20.2 | Medium |
| **P10.3 Challenge Failure Penalties** | Add failure-penalty fields to `Game` (with per-`Session` overrides): `fail_point_penalty`, `fail_cooloff_scaling`, `fail_tower_lockout_minutes`, `fail_difficulty_rollback`, `fail_counter_reset` (enum). New `TeamTowerFailCounter(team, tower, consecutive_fails, last_failed_at, locked_until)` (or derived from existing submissions) driving cooloff scaling + lockout + optional difficulty rollback. Score penalty applied atomically on REJECT. | 21.1 | Low |
