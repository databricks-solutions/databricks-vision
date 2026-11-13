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
# Every package comes from app/uv.lock with its hashes verified: the app's dependencies plus the
# `test` dependency group (pytest, ruff). The local projects (the app and image_gen.py) are not
# built or installed — tests import them straight from the source tree via PYTHONPATH — so no
# unpinned build backend runs either.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT/app"

# --inexact: leave anything else in a developer's existing .venv (e.g. editable installs) alone.
uv sync --frozen --group test --no-install-local --inexact --quiet
export PYTHONPATH="$REPO_ROOT/app/src:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "=== ruff ==="
uv run --frozen --no-sync ruff check "$REPO_ROOT"

echo "=== pytest ==="
if [ -z "${TEST_DATABASE_URL:-}" ]; then
  echo "  (TEST_DATABASE_URL not set — integration tests will be skipped)"
fi
MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen --no-sync pytest "$@"
