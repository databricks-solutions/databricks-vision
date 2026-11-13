#!/bin/bash
# test.sh — Python checks, exactly as CI runs them: ruff (fatal rules) + pytest.
#
# Usage: ./scripts/test.sh [pytest args...]      e.g. ./scripts/test.sh -k gallery -x
#
# Integration tests (app/tests/integration) need Postgres + pgvector and run only when
# TEST_DATABASE_URL is set; otherwise they skip. For example:
#
#   docker run --rm -d --name vision-test-pg -p 127.0.0.1:5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:pg17
#   TEST_DATABASE_URL=postgresql://postgres@localhost:5433/postgres ./scripts/test.sh
#
# Set REQUIRE_DB_TESTS=1 to fail (rather than skip) when no database is configured — CI does.
#
# Test tooling is pinned here and run ad hoc (`uv run --with` / `uvx`) so it never touches the
# lockfiles, which must keep resolving against public PyPI for people deploying this repo.

set -euo pipefail

RUFF_VERSION="0.17.4"
PYTEST_VERSION="9.2.0"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== ruff ${RUFF_VERSION} ==="
uvx "ruff@${RUFF_VERSION}" check .

echo "=== pytest ${PYTEST_VERSION} ==="
if [ -z "${TEST_DATABASE_URL:-}" ]; then
  echo "  (TEST_DATABASE_URL not set — integration tests will be skipped)"
fi
cd app
MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen --with "pytest==${PYTEST_VERSION}" pytest "$@"
