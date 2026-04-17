# Claude Code Development Guidelines — cercetador

Project-specific guidelines for AI assistants working on the `cercetador` Django app (a scouting geogame).

## Project Context

**Project Root**: `/home/yeti/projects/cercetador`

**Tech Stack**:
- Backend: Django 5.1 (Python 3.12)
- Geospatial: PostGIS + GeoDjango (`django.contrib.gis`), django-leaflet, DRF + `rest_framework_gis`
- Database: PostgreSQL with PostGIS extension (psycopg2 driver)
- Frontend: Django templates (being replaced by Angular v21 — see Phase 2 in `docs/plan.md`)
- Two Django apps:
  - `game` — Zone, Tower, Challenge, TeamTowerChallenge, ownership records
  - `organize` — Game, TeamGroup, Team, Player (per-game rosters)
- Project module: `geogame` (settings/urls/wsgi). Despite the repo root being named `cercetador`, the Python project module is `geogame`. `DJANGO_SETTINGS_MODULE=geogame.settings`.

**Python interpreter**: `/home/yeti/.virtualenvs/cercetador/bin/python` (Python 3.12.4, plain virtualenv — NOT pyenv). Runtime deps in `requirements.txt`, dev deps (coverage, ruff, ipython) in `requirements-dev.txt`.

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

- Run the full suite: `coverage run manage.py test game --noinput && coverage report --fail-under=80`
- Tests live in `game/tests.py`, organized by feature area (see file docstring).
- CI workflow: `.github/workflows/ci.yml` — PostGIS 3.4 service container, runs ruff + tests + coverage gate.
- Deploy workflow: `.github/workflows/deploy-geogame.yaml` — SSHes to prod VPS on push to main.

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

This project uses a structured docs system in [/docs](../docs/):

- [`docs/requirements.md`](../docs/requirements.md) — SOURCE OF TRUTH for system behavior, organized by functional area with user stories and SHALL-style acceptance criteria.
- [`docs/plan.md`](../docs/plan.md) — maps requirement sections to plan items (module/feature groups), with priority and linked requirements.
- [`docs/tasks.md`](../docs/tasks.md) — technical task list, `[x]`/`[ ]` checked, linked to plan items and requirements as `(Plan: X, Req: Y)`.

**When adding or modifying features:**
1. Check [requirements.md](../docs/requirements.md) first. If the feature isn't documented, ADD a new numbered requirement (user story + SHALL acceptance criteria) BEFORE coding.
2. Add or update a matching plan item in [plan.md](../docs/plan.md) linked to the requirement.
3. Add task(s) to [tasks.md](../docs/tasks.md) with `(Plan: X, Req: Y)` references.
4. Mark tasks `[x]` when done.
5. If behavior changes, update the relevant acceptance criteria in requirements.md at the same time.

**Open items** (not yet specified in detail) live at the bottom of [requirements.md](../docs/requirements.md) and as `T10.*` tasks in [tasks.md](../docs/tasks.md). These are blocked on requirements definition — ask the user for the intended behavior before implementing.

## Security

Assist with defensive security tasks only. Never commit credentials, API keys, or database passwords. The placeholder `SECRET_KEY` in `settings.py` predates this guideline and should be rotated if this project ever ships to production.
