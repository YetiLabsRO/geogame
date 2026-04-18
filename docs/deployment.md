# Deployment

Server-side provisioning and deploy workflow for [cercetador.albascout.ro](https://cercetador.albascout.ro).

The deploy is driven by GitHub Actions ([.github/workflows/deploy.yml](../.github/workflows/deploy.yml)): push to `main` → SSH to VPS → pull, install, migrate, collectstatic, restart gunicorn via supervisord, smoke-test `/health/`. This document covers everything the workflow assumes about the server.

---

## Architecture

```
Internet ──▶ nginx (443 TLS)
               ├── /static/  ─▶ files from /var/app/cercetador/staticfiles
               ├── /media/   ─▶ files from /var/app/cercetador/media
               └── /         ─▶ gunicorn (unix socket) ─▶ Django (geogame)
                    ├── /admin/
                    ├── /api/
                    └── /health/
```

- **Process manager**: supervisord (program name: `geogame`).
- **App server**: gunicorn, bound to a unix socket.
- **Reverse proxy + TLS**: nginx + Let's Encrypt (certbot).
- **DB**: PostgreSQL 16 with PostGIS extension, local Unix-socket auth.

## One-time VPS setup

Target OS: Ubuntu 24.04 LTS. All commands below run as `ubuntu` (sudo-capable).

### 1. System packages

```bash
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    build-essential git \
    gdal-bin libgdal-dev \
    postgresql postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    nginx supervisor \
    certbot python3-certbot-nginx \
    curl
```

### 2. PostgreSQL + PostGIS

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE geogame WITH LOGIN PASSWORD 'REPLACE_ME';
CREATE DATABASE geogame OWNER geogame;
\c geogame
CREATE EXTENSION IF NOT EXISTS postgis;
GRANT ALL ON SCHEMA public TO geogame;
SQL
```

Django's PostGIS migration (`game/migrations/0001_*`) has a commented-out `CreateExtension` because it needs superuser — installing the extension manually here is the required bootstrap.

### 3. App user + directory layout

```bash
sudo mkdir -p /var/app
sudo chown ubuntu:ubuntu /var/app
cd /var/app
git clone https://github.com/YetiLabsRO/geogame.git cercetador
cd cercetador
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install gunicorn
```

### 4. Environment file: `/etc/cercetador.env`

Secrets and per-host config live in a single env file owned by root, readable by the app user. The supervisord program loads it.

```bash
sudo tee /etc/cercetador.env >/dev/null <<'ENV'
DJANGO_SETTINGS_MODULE=geogame.settings
DB_NAME=geogame
DB_USER=geogame
DB_PASSWORD=REPLACE_ME
DB_HOST=127.0.0.1
DB_PORT=5432
BASE_URL=https://cercetador.albascout.ro
ENV
sudo chown root:ubuntu /etc/cercetador.env
sudo chmod 640 /etc/cercetador.env
```

Production-only overrides (`DEBUG=False`, `ALLOWED_HOSTS`, `SECRET_KEY`) go in `/var/app/cercetador/geogame/local_settings.py`, which is gitignored:

```python
# /var/app/cercetador/geogame/local_settings.py
import os

DEBUG = False
ALLOWED_HOSTS = ['cercetador.albascout.ro']
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']  # set in /etc/cercetador.env
CSRF_TRUSTED_ORIGINS = ['https://cercetador.albascout.ro']
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

Add `DJANGO_SECRET_KEY=...` to `/etc/cercetador.env`.

### 5. First run

```bash
cd /var/app/cercetador
set -a; . /etc/cercetador.env; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

### 6. supervisord program

```bash
sudo tee /etc/supervisor/conf.d/geogame.conf >/dev/null <<'CONF'
[program:geogame]
command=/var/app/cercetador/.venv/bin/gunicorn geogame.wsgi:application \
    --workers 3 \
    --bind unix:/run/geogame.sock \
    --access-logfile - \
    --error-logfile -
directory=/var/app/cercetador
user=ubuntu
group=www-data
umask=007
autostart=true
autorestart=true
stopsignal=TERM
stopwaitsecs=10
environment=PATH="/var/app/cercetador/.venv/bin:%(ENV_PATH)s"
stdout_logfile=/var/log/supervisor/geogame.out.log
stderr_logfile=/var/log/supervisor/geogame.err.log
CONF

# Load env file into the program's environment
sudo mkdir -p /etc/supervisor/conf.d
sudo sed -i '/^\[supervisord\]/a environment=$(cat /etc/cercetador.env | tr "\n" ",")' /etc/supervisor/supervisord.conf || true

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start geogame
```

Allow the CI user (`ubuntu`) to restart gunicorn without a password — the deploy workflow relies on this:

```bash
sudo tee /etc/sudoers.d/geogame-deploy >/dev/null <<'SUDO'
ubuntu ALL=(root) NOPASSWD: /usr/bin/supervisorctl start geogame, /usr/bin/supervisorctl stop geogame, /usr/bin/supervisorctl restart geogame
SUDO
sudo chmod 440 /etc/sudoers.d/geogame-deploy
```

### 7. nginx server block

```bash
sudo tee /etc/nginx/sites-available/cercetador >/dev/null <<'NGINX'
upstream geogame_app {
    server unix:/run/geogame.sock;
}

server {
    listen 80;
    server_name cercetador.albascout.ro;
    # certbot will rewrite this block to add :443 + TLS
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name cercetador.albascout.ro;

    client_max_body_size 20M;  # challenge photo uploads

    location /static/ {
        alias /var/app/cercetador/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias /var/app/cercetador/media/;
        access_log off;
        expires 7d;
    }

    location /health/ {
        proxy_pass http://geogame_app;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        access_log off;
    }

    location / {
        proxy_pass http://geogame_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
}
NGINX

sudo ln -s /etc/nginx/sites-available/cercetador /etc/nginx/sites-enabled/cercetador
sudo nginx -t && sudo systemctl reload nginx
```

The dedicated `/health/` location block exists so nginx logs stay quiet (`access_log off`) and so the endpoint can be sanity-checked even if you later move the main `location /` to serve a static Angular build. `/health/` must always reach Django — it's the deploy workflow's smoke test.

### 8. TLS via Let's Encrypt

```bash
sudo certbot --nginx -d cercetador.albascout.ro \
    --non-interactive --agree-tos -m admin@albascout.ro
sudo systemctl enable --now certbot.timer
```

Certbot edits the nginx config in-place to add port 443 + TLS directives. Re-run `certbot renew --dry-run` afterwards to confirm renewal works.

## GitHub deploy workflow

[.github/workflows/deploy.yml](../.github/workflows/deploy.yml) triggers on every push to `main` (and on manual `workflow_dispatch`).

Required GitHub `production` environment config:

| Kind | Name | Value |
| :--- | :--- | :--- |
| Variable | `SSH_HOST` | VPS hostname (e.g. `geocode.albascout.ro`) |
| Variable | `SSH_USER` | `ubuntu` |
| Variable | `SSH_PORT` | `22` |
| Secret | `SSH_KEY` | Private OpenSSH key authorized for `ubuntu@<host>` |

The workflow steps:

1. Configures SSH with the key from secrets.
2. `supervisorctl stop geogame` (brief downtime — acceptable for this event-scale app).
3. `git fetch && git reset --hard origin/main`.
4. `pip install -r requirements.txt`.
5. `manage.py migrate --noinput`.
6. `manage.py collectstatic --noinput`.
7. `supervisorctl start geogame` (runs even if prior steps fail, so the site isn't left down).
8. **Smoke test**: `curl -fsS https://cercetador.albascout.ro/health/` with 5 retries. Fails the workflow if `/health/` returns non-2xx.

## Verifying `/health/`

After a deploy, confirm from any machine:

```bash
curl -i https://cercetador.albascout.ro/health/
# HTTP/2 200
# {"status": "ok"}
```

If it returns 503, the view reached Django but couldn't `SELECT 1` from PostgreSQL — check the DB is running and `/etc/cercetador.env` has the right credentials. If it returns 502, gunicorn isn't responding — check `sudo supervisorctl status geogame` and the error log at `/var/log/supervisor/geogame.err.log`.

## Rollback

```bash
ssh ubuntu@geocode.albascout.ro
cd /var/app/cercetador
sudo supervisorctl stop geogame
git reset --hard <previous-sha>
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
sudo supervisorctl start geogame
curl -f https://cercetador.albascout.ro/health/
```

Migrations are forward-only — a rollback to a commit with a missing migration will leave the DB ahead of the code. For schema-changing releases, keep a DB snapshot (`pg_dump`) before the deploy.
