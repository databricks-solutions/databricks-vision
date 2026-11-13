# Contributing

Thanks for your interest in contributing to Databricks Vision. This project is maintained by the Databricks Field Engineering team on a best-effort basis.

## Reporting bugs and requesting features

Open a [GitHub issue](https://github.com/databricks-solutions/databricks-vision/issues). For bugs, please include:

- Repro steps and observed vs expected behaviour.
- Deploy target (`databricks.yml` target name, workspace cloud, Lakebase variant).
- Relevant log excerpts from `databricks apps logs databricks-vision -p <profile>`.

For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead — do not file them as public issues.

## Pull requests

1. Open an issue describing the change first so we can align on direction before you spend time on a PR.
2. Fork the repo and create a feature branch.
3. Match the style of the surrounding code:
   - Python: 3.11+, type hints, `ruff`-friendly. `image_gen.py` is the single source of truth for library logic.
   - TypeScript/React: use the existing `@/components/ui` primitives and TanStack Router conventions.
4. Run the checks CI runs (see [Running the checks locally](#running-the-checks-locally)).
5. If you changed `databricks.yml`, verify the bundle still validates: `databricks bundle validate -t dev -p <profile>`.
6. Open the PR with a clear description and link the issue. CI must pass before review.

## Running the checks locally

CI (`.github/workflows/ci.yml`) runs on every PR without any Databricks credentials. To run the same checks:

```bash
# Python: ruff + pytest. Integration tests need Postgres + pgvector, or they are skipped.
docker run --rm -d --name vision-test-pg -p 127.0.0.1:5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres@localhost:5433/postgres ./scripts/test.sh

# Frontend: typecheck + production build (fails if Tailwind is dropped from the bundle)
cd app && bun install --frozen-lockfile && bun run typecheck && cd .. && ./scripts/build-frontend.sh
```

- Unit tests live in `app/tests/`; tests that need a database go in `app/tests/integration/`. Each run creates and drops its own `vision_test_*` database, so it never touches existing data. It refuses to run against a Databricks-hosted host.
- Tests never call model serving, Lakebase or a real workspace. Routes run against a fake `WorkspaceClient` (`app/tests/fakes.py`) and a local Postgres pool.

### Lockfiles

`uv.lock`, `app/uv.lock` and `app/bun.lock` must resolve against **public** PyPI and npm, because GitHub runners and external users can't reach internal mirrors. CI fails if a lockfile references `pypi-proxy` or `npm-proxy`. If your network forces a mirror, don't commit the re-resolved lockfile your deploy build produces. To add a dependency, re-lock and then map the mirror URLs back to `https://pypi.org/simple` / `https://files.pythonhosted.org/packages/` (uv), or to `""` (bun's default-registry form). The file paths are identical.

## Code review and merging

PRs are reviewed by a maintainer (see [.github/CODEOWNERS](.github/CODEOWNERS)). Reviews are best-effort — please allow up to a week.

## Security and hygiene

Before submitting a PR:

- Don't commit `.env`, `.databricks/`, workspace identifiers, customer names, or any internal Databricks infrastructure URLs.
- The repo has GitHub secret scanning and push protection enabled. If push protection blocks your push, treat it as a real finding — rotate the credential before working around it.
- Run `rg -i '<your-workspace>|<your-catalog>'` on your branch before pushing to confirm placeholders were filled in for local testing only and reverted.

## License

By contributing, you agree that your contributions will be licensed under the [Databricks License](LICENSE.md) that covers this repo.
