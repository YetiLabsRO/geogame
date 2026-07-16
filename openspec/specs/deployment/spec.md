# Deployment & Infrastructure Specification

## Purpose

Define the infrastructure contract: PostGIS bootstrapping, CI (lint + tests + coverage gate), automated deploy to the VPS, and a health-check endpoint for monitors.

## Requirements

### Requirement: PostGIS bootstrapping

The system SHALL install the PostGIS extension as part of the migration flow when permitted.

#### Scenario: Superuser role

- **WHEN** the deploying database role has superuser privileges and `manage.py migrate` runs
- **THEN** the system SHALL install the PostGIS extension

#### Scenario: Non-superuser role

- **WHEN** the deploying role does NOT have superuser privileges
- **THEN** the extension MUST be created out-of-band by a superuser before running migrations (documented caveat)

### Requirement: Continuous integration

The system SHALL run lint, tests, and a coverage gate on every push and pull request.

#### Scenario: CI run

- **WHEN** code is pushed or a pull request is opened
- **THEN** `.github/workflows/ci.yml` SHALL configure a Python 3.12 + PostgreSQL/PostGIS environment, run `ruff check .`, and run `manage.py test game --noinput` with coverage
- **AND** the workflow SHALL fail if branch coverage drops below 80% or if `ruff check` finds violations

### Requirement: Automated deploy to VPS

The system SHALL deploy to production automatically on push to `main`.

#### Scenario: Deploying on push to main

- **WHEN** a commit is pushed to `main`
- **THEN** a GitHub Actions workflow SHALL SSH to the VPS at `cercetador.albascout.ro`, pull the latest code, install dependencies, run migrations, collect static files, and reload the gunicorn systemd unit
- **AND** it SHALL run `curl -f https://cercetador.albascout.ro/health/` after reload and fail the deployment if the health check does not return 200
- **AND** secrets SHALL be stored in GitHub repository secrets (`SSH_HOST`, `SSH_USER`, `SSH_KEY`, `DEPLOY_PATH`)

### Requirement: Health-check endpoint

The system SHALL expose an unauthenticated health-check endpoint reporting database reachability.

#### Scenario: Healthy and unhealthy responses

- **WHEN** a monitor requests `GET /health/`
- **THEN** the system SHALL return HTTP 200 with `{"status": "ok"}` when it can reach the database
- **AND** it SHALL return HTTP 503 when the database is unreachable
- **AND** the endpoint SHALL NOT require authentication
