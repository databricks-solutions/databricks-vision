## Summary

<!-- What changes and why. Link the issue if there is one. -->

## Testing

<!-- CI runs ruff, pytest (unit + Postgres/pgvector integration), the frontend typecheck/build and
     the wheel build. Tick what you ran beyond that. -->

- [ ] `./scripts/test.sh` (with `TEST_DATABASE_URL` set, if you touched SQL or routes)
- [ ] `cd app && bun run typecheck` (if you touched the UI)
- [ ] Deployed to a dev target and checked the app (`./scripts/deploy.sh <target> <profile>`)
- [ ] `databricks bundle validate` (if you touched `databricks.yml`)

## Checklist

- [ ] No workspace hosts, catalog names, customer names or internal URLs committed
- [ ] Lockfiles still resolve against public PyPI / npm (CI fails otherwise)
