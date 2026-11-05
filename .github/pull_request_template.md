<!-- Read .github/CONTRIBUTING.md first. Write "none" in any section that does not apply. -->

## What

<!-- One paragraph. -->

## Why

<!-- The problem this solves. -->

Closes #

## How

<!-- The approach, and any decision that is not obvious. -->

## Testing

<!-- What you ran, and what you checked by hand. -->

## Checklist

- [ ] Branched from `dev` and targets `dev`
- [ ] `python manage.py check` passes
- [ ] `python manage.py makemigrations --check --dry-run` passes
- [ ] `python manage.py test` passes
- [ ] Migrations are committed, if models changed
- [ ] New or changed environment variables are in `env.example` and `docs/reference/configuration.md`
- [ ] `AGENTS.md` or a skill in `.agents/skills/` is updated, if a command or trap changed
- [ ] PRs in other repos are linked, with the deploy order

## AI assistance

<!-- Did an AI coding agent write part of this? Name it, and say what you verified by hand. -->
