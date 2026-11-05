---
name: run-backend
description: Start the Socratic Bots backend locally — Django on port 8001 — and check the DARE backend and shared keys it depends on. Use when the user wants to run, start, boot, or serve the Socratic Bots / socraticbots backend, or asks why the API on :8001 rejects every request.
---

# Run the Socratic Bots backend

A Django REST API on `http://localhost:8001/api/`. It cannot do anything useful without a DARE
backend on `http://localhost:8000`: sign-in, chat, files, and billing all go through DARE.

## Before starting

1. **DARE is up.** `curl -s http://localhost:8000/api/health/` should answer. If not, the user
   needs DARE running first (see the dare-backend repo).
2. **`.env` exists at the repo root.** If not: `cp env.example .env`.
3. **Shared keys match DARE.** `SSO_JWT_KEY` and `DARE_INTERNAL_KEY` in this `.env` must equal
   the values in DARE's `.env`. A mismatch is the most common failure: login works, then every
   call returns 401.

## Local Python

```bash
python3 -m venv venv              # first time only; Python 3.10+
source venv/bin/activate
pip install -r requirements.txt   # first time, or after requirements change
cd backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

Run Django commands from `backend/`. With `DB_HOST` empty the database is SQLite at
`backend/db.sqlite3`.

If startup fails with `OSError: cannot load library ...`, WeasyPrint's system libraries are
missing: `brew install pango` on macOS, `apt install libpango-1.0-0 libpangoft2-1.0-0` on
Debian/Ubuntu.

## Docker

```bash
docker compose up --build -d
docker compose exec web python backend/manage.py migrate
```

Runs the API on `:8001` with PostgreSQL on `:5433`. The container reaches DARE at
`http://host.docker.internal:8000` (override with `DOCKER_DARE_BACKEND_URL`).

## Running it in the background

From an agent session, detach so the server outlives the session:

```bash
cd backend
nohup ../venv/bin/python manage.py runserver 0.0.0.0:8001 > /tmp/socraticbots-backend.log 2>&1 & disown
```

## Verify

```bash
curl -i http://localhost:8001/api/users/me/
```

`401 Unauthorized` means Django is serving. There is no unauthenticated health endpoint.

## Stop

```bash
lsof -ti tcp:8001 | xargs kill    # local
docker compose down               # Docker
```

## Related

- `check` — run before opening a PR.
- The frontend (socraticbots-frontend) runs on `:5174` and needs this backend plus DARE.
- `docs/tutorials/quickstart.md` has the full-stack walkthrough and a troubleshooting table.
