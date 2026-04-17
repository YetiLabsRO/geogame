# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Quick facts
- Django 5.1 scouting geogame. Two apps:
  - `game` — Zone, Tower, Challenge, TeamTowerChallenge, ownership records
  - `organize` — Game, TeamGroup, Team, Player (per-game team rosters)
- Project module: `geogame` (settings / urls / wsgi live here). **Not** `cercetador` despite the repo directory name.
- Python interpreter: `/home/yeti/.virtualenvs/cercetador/bin/python` (Python 3.12, plain virtualenv)
- Database: PostgreSQL + PostGIS
- Dev server default port: 8000
- Main branch: `main`

## Common commands
```bash
# Dev server
/home/yeti/.virtualenvs/cercetador/bin/python manage.py runserver 8000

# Tests + coverage (matches CI)
/home/yeti/.virtualenvs/cercetador/bin/coverage run manage.py test game --noinput
/home/yeti/.virtualenvs/cercetador/bin/coverage report --fail-under=80

# Lint (matches CI)
/home/yeti/.virtualenvs/cercetador/bin/ruff check .

# Migrations
/home/yeti/.virtualenvs/cercetador/bin/python manage.py migrate
/home/yeti/.virtualenvs/cercetador/bin/python manage.py makemigrations
```

VS Code launch configs in [.vscode/launch.json](.vscode/launch.json) wrap these with the debugger.

## Before you code
- Read [.claude/guidelines.md](.claude/guidelines.md) for style and testing notes
- Read [docs/requirements.md](docs/requirements.md) — SOURCE OF TRUTH for system behavior. Check it before changing behavior; update it first if adding new behavior.
- [docs/plan.md](docs/plan.md) maps requirements to modules; [docs/tasks.md](docs/tasks.md) tracks work. When adding a feature: update requirements → plan → tasks in that order.
- Teams belong to a `TeamGroup` per-game (not the legacy EXPLORATORI/TEMERARI/SENIORI hardcoded categories). Each Game has its own TeamGroups.
- Runtime deps in `requirements.txt`; dev deps (coverage, ruff, ipython) in `requirements-dev.txt`.
- `geogame/local_settings.py` is gitignored and overrides `geogame/settings.py` — don't commit secrets.
