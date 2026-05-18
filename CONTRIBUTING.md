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
4. Verify the app still builds locally: `cd app && uv sync && bun install && apx build .`.
5. Verify the bundle still validates: `databricks bundle validate -t dev -p <profile>`.
6. Open the PR with a clear description and link the issue.

## Code review and merging

PRs are reviewed by a maintainer (see [CODEOWNERS.txt](CODEOWNERS.txt)). Reviews are best-effort — please allow up to a week.

## Security and hygiene

Before submitting a PR:

- Don't commit `.env`, `.databricks/`, workspace identifiers, customer names, or any internal Databricks infrastructure URLs.
- The repo has GitHub secret scanning and push protection enabled. If push protection blocks your push, treat it as a real finding — rotate the credential before working around it.
- Run `rg -i '<your-workspace>|<your-catalog>'` on your branch before pushing to confirm placeholders were filled in for local testing only and reverted.

## License

By contributing, you agree that your contributions will be licensed under the [Databricks License](LICENSE.md) that covers this repo.
