#!/bin/bash
# deploy.sh — Full deploy workflow for databricks-vision.
# Chains: render-app-yml → bundle deploy → post-deploy (DB + UC + MLflow setup) → bundle run → smoke test
#
# Usage: ./scripts/deploy.sh <target> [profile]
#
#   target   a key under `targets:` in databricks.yml
#   profile  Databricks CLI profile. Optional: defaults to DATABRICKS_CONFIG_PROFILE from
#            deploy/<target>.env, then to environment auth (CI), then to DEFAULT.
#
# Examples:
#   ./scripts/deploy.sh dev DEFAULT
#   ./scripts/deploy.sh vision-dev          # profile + variables from deploy/vision-dev.env
#
# Set SKIP_SMOKE_TEST=1 to skip the final smoke test.

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/_common.sh
source "$SCRIPT_DIR/_common.sh"
cd "$REPO_ROOT"

# uv defaults to public PyPI. On networks where pypi.org is blocked, export
# UV_INDEX_URL to a mirror before running this script.

echo "=== 0/4 Render app/app.yml from template ==="
./scripts/render-app-yml.sh "$TARGET"

echo "=== 1/4 Bundle deploy (target=$TARGET) ==="
databricks bundle deploy -t "$TARGET"

echo "=== 2/4 Post-deploy (Lakebase, UC grants, MLflow experiment) ==="
./scripts/post-deploy.sh "$TARGET"

echo "=== 3/4 Starting app ==="
databricks bundle run databricks-vision-app -t "$TARGET"

if [ "${SKIP_SMOKE_TEST:-}" = "1" ]; then
  echo "=== 4/4 Smoke test skipped (SKIP_SMOKE_TEST=1) ==="
else
  echo "=== 4/4 Smoke test ==="
  APP_NAME=$(databricks bundle summary -t "$TARGET" -o json | jq -er '.resources.apps["databricks-vision-app"].name')
  run_py scripts/smoke_test.py --app "$APP_NAME"
fi

echo "=== Deploy complete ==="
