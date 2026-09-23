# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Quick facts
- Django 5.1 scouting geogame. Two apps:
  - `game` — Zone, Tower, Challenge, TeamTowerChallenge, ownership records
  - `organize` — Game, TeamGroup, Team, Player (per-game team rosters)
- Project module: `geogame` (settings / urls / wsgi live here). **Not** `cercetador` despite the repo directory name.
- Python interpreter: `/home/yeti/.virtualenvs/cercetador/bin/python` (Python 3.12, plain virtualenv)
- Database: PostgreSQL + PostGIS
- Dev server default port: 8200 (player SPA 4500, staff SPA 4501)
- Main branch: `main`

## Common commands
```bash
# Dev server
/home/yeti/.virtualenvs/cercetador/bin/python manage.py runserver 8200

# Tests + coverage (matches CI)
/home/yeti/.virtualenvs/cercetador/bin/coverage run manage.py test game organize simulator authoring --noinput
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
- Planning/specs live in [OpenSpec](openspec/). `openspec/specs/<capability>/spec.md` is the SOURCE OF TRUTH for shipped behavior; in-flight work lives as change proposals under `openspec/changes/`. Browse with `openspec spec list` / `openspec list`, read with `openspec show <name>`.
- When adding or changing behavior, create a change proposal first (`/opsx:propose` or `openspec new change "<name>"`) — proposal + delta specs + tasks — then implement, then archive (`/opsx:archive`) to fold the deltas into the main specs. Don't edit `openspec/specs/` by hand for new behavior; that's what archiving a change does.
- Teams belong to a `TeamGroup` per-game (not the legacy EXPLORATORI/TEMERARI/SENIORI hardcoded categories). Each Game has its own TeamGroups.
- Runtime deps in `requirements.txt`; dev deps (coverage, ruff, ipython) in `requirements-dev.txt`.
- `geogame/local_settings.py` is gitignored and overrides `geogame/settings.py` — don't commit secrets.
