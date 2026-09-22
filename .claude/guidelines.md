# Claude Code Development Guidelines — cercetador

Project-specific guidelines for AI assistants working on the `cercetador` Django app (a scouting geogame).

## Project Context

**Project Root**: `/home/yeti/projects/cercetador`

**Tech Stack**:
- Backend: Django 5.1 (Python 3.12)
- Geospatial: PostGIS + GeoDjango (`django.contrib.gis`), django-leaflet, DRF + `rest_framework_gis`
- Database: PostgreSQL with PostGIS extension (psycopg2 driver)
- Frontend: Angular v21 workspace at `frontend/` — two apps (`player`, `staff`) plus a `shared` library. Bootstrap 5 + bootstrap-icons + Leaflet. Token auth via the `tokenInterceptor` from the `shared` lib.
- Two Django apps:
  - `game` — Zone, Tower, Challenge, TeamTowerChallenge, ownership records
  - `organize` — Game, TeamGroup, Team, Player (per-game rosters)
- Project module: `geogame` (settings/urls/wsgi). Despite the repo root being named `cercetador`, the Python project module is `geogame`. `DJANGO_SETTINGS_MODULE=geogame.settings`.

**Python interpreter**: `/home/yeti/.virtualenvs/cercetador/bin/python` (Python 3.12.4, plain virtualenv — NOT pyenv). Runtime deps in `requirements.txt`, dev deps (coverage, ruff, ipython) in `requirements-dev.txt`.

**Node / Angular**: Node 20.19+ / npm 10.8+. Angular CLI v21.2 (dev dependency of `frontend/`).

## Path Guidelines
- ALWAYS use Linux-style paths with forward slashes `/`
- Project root is `/home/yeti/projects/cercetador`
- NEVER use Windows-style paths (e.g., `C:\...` or `\\wsl.localhost\...`)
- If you see a Windows path in any output, IMMEDIATELY convert it to its Linux equivalent

## Running the Project

The `.envrc` (loaded by direnv) activates the virtualenv and starts postgres. When working outside direnv, invoke Python directly:

```bash
# Run the dev server
/home/yeti/.virtualenvs/cercetador/bin/python manage.py runserver 8000

# Migrations
/home/yeti/.virtualenvs/cercetador/bin/python manage.py migrate
/home/yeti/.virtualenvs/cercetador/bin/python manage.py makemigrations

# Run tests
/home/yeti/.virtualenvs/cercetador/bin/python manage.py test --verbosity=2 --noinput

# Shell
/home/yeti/.virtualenvs/cercetador/bin/python manage.py shell
```

VS Code launch configurations in `.vscode/launch.json` wrap these same commands with the debugger attached.

## Database Notes

- PostGIS extension required. The initial migration tries to install it; this needs DB superuser. For local dev, ensure the `postgres` role has superuser or create the extension manually.
- Connection settings come from env vars with defaults in `geogame/settings.py` (host 127.0.0.1, port 5432, db `geogame`).
- `geogame/local_settings.py` is gitignored and overrides defaults.

## Tests & CI

- Run the full suite: `coverage run manage.py test game organize --noinput && coverage report --fail-under=80`
- Backend tests live in `game/tests.py` and `organize/tests.py`, organized by feature area.
- CI workflow: `.github/workflows/ci.yml` — PostGIS 3.4 service container, runs ruff + tests + coverage gate.
- Deploy workflow: `.github/workflows/deploy.yml` — SSHes to prod VPS on push to main, runs the `/health/` smoke test.

## Frontend (Angular v21)

The Angular workspace lives at `frontend/`:
- **Projects**: `player` (default, dev port 4500), `staff` (dev port 4501), `shared` (library — `AuthService`, `tokenInterceptor`, and reusable components).
- **Styles**: Bootstrap 5 via node_modules, Leaflet CSS, bootstrap-icons. No ng-bootstrap; use plain Bootstrap classes + the bundled JS.
- **TypeScript path**: `import { AuthService, tokenInterceptor } from 'shared';` — maps to `projects/shared/src/public-api.ts` at build time (see [tsconfig.json](../frontend/tsconfig.json)).
- **Dev proxy**: [frontend/proxy.conf.json](../frontend/proxy.conf.json) routes `/api/`, `/admin/`, `/media/`, `/static/`, `/health/` to Django on `:8200`. Start Django on 8200 before `npm start`. (E2E tests still run against `:8000` / `:4200` / `:4201` — see playwright.config.ts.)

Common commands (run from `frontend/`):

```bash
npm start                 # player on :4500 (proxies to Django on :8200); launch configs use --port 4500/4501
npm run start:staff       # staff on :4501
npm run build:all         # build both apps → frontend/dist/{player,staff}
npx ng generate component some-name --project=player
```

### Design system & platform layer (mobile-app)

- **Player screens** are built from `shared/src/lib/ui` (`ui-button`, `ui-chip`, `ui-field`+`uiInput`, `ui-card`, `ui-stat-tile`, `ui-progress-meter`, `ui-avatar`, `ui-top-app-bar`, `ui-bottom-nav`, `ui-toast-outlet`/`ToastService`, `ui-empty-state`, `ui-alert`, `ui-spinner`, `ui-icon`) and the `.tr-*` typography utilities; colours/spacing/radius come only from the CSS custom properties in `shared/src/lib/theme/_tokens.scss` (light + dark). Team identity uses the runtime `--team-color` slot. The contract is [docs/design-system.md](../docs/design-system.md); `/dev/gallery` (dev builds) shows every component in both themes. The staff app still uses full Bootstrap.
- **Bootstrap in the player** = grid, flex/spacing utilities and reboot only. No component classes (`btn`, `card`, `alert`, `badge`, `form-control`, `list-group`, `navbar`, `progress`, `modal`, `spinner-border`) and no Bootstrap colour utilities.
- **Platform layer**: everything device-related is a service in `shared/src/lib/platform` that picks the Capacitor plugin on native and the browser API on the web (`PlatformService`, `GeolocationService`, `BackgroundLocationService`, `PushBridge`, `NfcService`, `HapticsService`, `KeepAwakeService`, `NetworkService`, `DeepLinkService`, `BleProximityService`). Screens never touch `navigator.geolocation`, `NDEFReader`, `PushManager`, `wakeLock` or `@capacitor/*` directly. Relative `/api`/`/media`/websocket URLs resolve against `PlatformService.apiBaseUrl()` (empty on the web, `environment.nativeApiBaseUrl` in the shell, debug override via Preferences).
- **Native shell**: `frontend/capacitor.config.ts`; `npm run cap:sync[:dev]` builds the player and syncs `android/` + `ios/`; native code that must be committed lives in `android/app/src/main/java/ro/yetilabs/geogame` and `ios/App/App` (local `BleAdvertiser` plugin). See [docs/mobile.md](../docs/mobile.md) for Firebase, signing, app links and the iOS (macOS-only) steps.

### MCP

[.mcp.json](../.mcp.json) at the repo root registers two MCP servers for Claude Code:
- `angular-cli` — Angular CLI MCP, exposes `ng generate`, docs lookups, and project introspection.
- `chrome-devtools` — Chrome DevTools MCP, lets you drive a real browser to exercise the running app.

Both are launched via `npx -y` on demand; no global install needed.

### E2E (Playwright)

Specs live in [frontend/e2e/](../frontend/e2e/). They cover the player journey
(invite → register → submit challenge) and the staff journey (create invite →
review → confirm → tower color update).

First-time setup (installs the Chromium browser + OS deps):
```bash
cd frontend
npm run e2e:install
```

Running the specs (the `globalSetup` calls `manage.py seed_e2e_fixture` which
resets a deterministic set of e2e-prefixed rows, so it's safe to rerun):
```bash
# Start the backend and both dev servers in separate terminals:
/home/yeti/.virtualenvs/cercetador/bin/python manage.py runserver 8000
cd frontend && npm run start:player
cd frontend && npm run start:staff

# Then from frontend/:
npm run e2e         # headless
npm run e2e:ui      # interactive runner
```

CI can set `PLAYWRIGHT_MANAGED=1` to let Playwright start all three servers
itself (see [playwright.config.ts](../frontend/playwright.config.ts)).

### Angular style

- Use **standalone components** (default in v21). Avoid NgModules.
- Use **signals** for reactive state; `computed()` / `effect()` instead of RxJS where possible. Keep Observables for HTTP.
- Template control flow: `@if` / `@for` / `@switch` instead of `*ngIf`/`*ngFor`.
- Import shared code via `import { ... } from 'shared';` — never relative `../../shared/...`.
- Prettier config is in `frontend/package.json` (100 char, single quotes).

## Django Style

- Django 5.2 conventions (Phase 0 upgraded from Django 3.1 — modern APIs are fine)
- Follow PEP 8 with 120 character line limit (`pyproject.toml` configures ruff)
- Use single quotes for strings (matches existing code style in this repo — unlike weinland)
- Use f-strings for formatting
- Prefer Django ORM over raw SQL
- Add `__str__` to every model
- Use `select_related` / `prefetch_related` to avoid N+1
- Always use migrations for schema changes
- Never commit secrets; `SECRET_KEY` in `settings.py` is a dev-only placeholder and should be overridden via `local_settings.py` in production

## Testing

- Run the full suite with `manage.py test --noinput`
- Tests live in `geogame/tests.py` (organized by feature area; see file docstring)
- Coverage: `coverage run manage.py test geogame --noinput && coverage report --fail-under=80`
- CI (see `.github/workflows/ci.yml`) enforces ≥80% branch coverage + `ruff check`
- ALWAYS run affected tests before declaring a task done
- Write both positive and negative test cases for new features

## Working on geogame

Key models to be aware of (see `geogame/models.py`):
- Towers, Challenges, Teams, TowerControl, scoring / bonus points
- Challenge difficulty calculation and "next challenge" assignment logic have dedicated tests — run them after touching scoring code

## Git / Workflow

- Main branch: `main`
- Commit messages: reference the issue number with `#N` prefix when applicable (matches existing style: `#1 removed CreateExtension...`)
- Do NOT amend published commits; create new ones
- Do NOT skip hooks (`--no-verify`) unless explicitly asked

## Task Tracking & Requirements

This project uses [OpenSpec](../openspec/) (schema `spec-driven`) for planning and specs.

- [`openspec/specs/<capability>/spec.md`](../openspec/specs/) — SOURCE OF TRUTH for shipped behavior. One capability per file (e.g. `scoring`, `sessions`, `challenge-submission`); each holds `### Requirement:` blocks with SHALL statements and `#### Scenario:` (WHEN/THEN) cases. List with `openspec spec list`, read with `openspec show <capability>`.
- [`openspec/changes/<name>/`](../openspec/changes/) — in-flight proposals not yet shipped, each with `proposal.md`, `design.md`, delta `specs/`, and `tasks.md`. The Phase 10 work (day pausing + challenge-failure consequences) lives in `changes/day-pausing-and-failure-consequences/`. List with `openspec list`.

**When adding or modifying features** (use the `/opsx:*` slash commands, backed by the `openspec-*` skills):
1. `/opsx:propose "<idea>"` (or `openspec new change "<name>"`) to scaffold a change; author `proposal.md`, delta `specs/` (`## ADDED/MODIFIED/REMOVED Requirements`), and `tasks.md`. Do this BEFORE coding.
2. Implement against the tasks (`/opsx:apply`), checking off `- [ ]` items as you go.
3. Validate with `openspec validate <name> --strict`.
4. When shipped, `/opsx:archive` folds the delta specs into `openspec/specs/` (or `/opsx:sync` to update main specs without archiving). Do NOT hand-edit `openspec/specs/` for new behavior.

**Open items** not yet specified in detail become new change proposals — ask the user for the intended behavior before implementing.

## Security

Assist with defensive security tasks only. Never commit credentials, API keys, or database passwords. The placeholder `SECRET_KEY` in `settings.py` predates this guideline and should be rotated if this project ever ships to production.
