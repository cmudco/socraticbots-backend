---
name: check
description: Run the Socratic Bots backend's pre-PR checks — Django system check, missing-migration check, and the test suite — and review the diff against docs/reference/rules.md. Use before committing, before opening a pull request, or when the user asks whether a backend change is ready.
---

# Check a backend change

Run from `backend/` with the virtualenv active. The suite uses SQLite and needs no DARE, Redis,
or network.

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

All three must pass. The tests read `SSO_JWT_KEY` and `DARE_INTERNAL_KEY`; any non-empty value
works, and the repo-root `.env` provides them. Run tests from `backend/` — discovery from the repo
root silently misses them.

To run one app or test: `python manage.py test voice` or
`python manage.py test voice.test_api_contract`.

## Review the diff

Check the change against `docs/reference/rules.md`, especially:

- DARE calls only through `backend/utils/dare_api/` clients.
- Internal endpoints decorated with `@require_internal_key`; their payloads stay snake_case.
- Every view declares permissions and scopes its queryset to the requesting user.
- Model changes come with their migration.
- New environment variables are added to `core/settings.py`, `env.example`, and
  `docs/reference/configuration.md` together.
- No LLM, embedding, or vector-store code: that belongs in DARE.

Report what passed, what failed with the failing test names, and any docs/reference/rules.md issues in the diff.
