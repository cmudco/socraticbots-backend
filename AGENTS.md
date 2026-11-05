# AGENTS.md

Django REST backend for Socratic Bots on port 8001. It stores tutors, access codes, notes and voice
agents, and proxies everything else to the DARE backend on :8000. It has no LLM, embedding or
vector-store code — chat, retrieval and billing belong in DARE.

Read and follow `docs/reference/rules.md` before changing code. Procedures live in `.agents/skills/`:
`run-backend`, `check`.

## Commands

```bash
cp env.example .env                                 # repo root; set SSO_JWT_KEY, DARE_INTERNAL_KEY
cd backend && python manage.py migrate
python manage.py runserver 0.0.0.0:8001
python manage.py test                               # 78 tests, SQLite, ~15 s, no network
python manage.py check
python manage.py makemigrations --check --dry-run   # no missing migrations
```

## Traps

- **`SSO_JWT_KEY` empty means every request is a 401.** It must equal DARE's value; otherwise
  sign-in looks fine and every call after it is anonymous, even with a valid DARE token.
- **`DARE_INTERNAL_KEY` must match DARE and the voice runtime.** With `DEBUG=True` it defaults to
  `local-dev-internal-key`, DARE's local default; empty rejects every internal call.
- **Deployment hosts live in env, never in code.** `backend/core/settings.py` only builds in
  localhost. A real domain goes in `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`.
- **DARE calls go through `backend/utils/dare_api/` only.** Add a method to the right client; never
  call DARE with `requests` or `httpx` elsewhere.
- **The runtime session-context endpoint answers in snake_case.** `voice_runtime_session_context` in
  `backend/voice/api/runtime_views.py` bypasses the camelCase renderer because the voice runtime
  reads snake_case keys. Keep that override; everything else, `api/bots/internal/*` included, is
  camelCase.
- **WeasyPrint system libraries are required to start.** `voice/api/views.py` imports WeasyPrint when
  the URLs load, so missing Pango/HarfBuzz stops the whole app.
- **There is no CI.** The repo has no `.github/workflows/`; run the `check` skill yourself.
- **Run tests from `backend/`.** Discovery from the repo root misses them. Tests use Django's runner
  (no pytest) and live in `tests.py` or `test_*.py` beside each app's code.
- **Freeze `voice.services.session_service.timezone.now` in voice tests that pin dates.** Otherwise
  the stale-attempt sweep expires the fixtures.
- **`createsuperuser` here makes an admin-only user.** It has no DARE link; real users are created
  on first sign-in through DARE.
