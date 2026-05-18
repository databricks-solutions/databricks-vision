#!/bin/bash
# deploy.sh — Full deploy workflow for databricks-vision.
# Chains: render-app-yml → bundle deploy → post-deploy (resources + DB grants) → bundle run
#
# Usage: ./scripts/deploy.sh <target> [profile]
#
# Example:
#   ./scripts/deploy.sh dev DEFAULT

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-DEFAULT}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# uv defaults to public PyPI. On networks where pypi.org is blocked, export
# UV_INDEX_URL to a mirror before running this script.

echo "=== 0/4 Render app/app.yml from template ==="
./scripts/render-app-yml.sh "$TARGET" "$PROFILE"

echo "=== 1/4 Bundle deploy (target=$TARGET, profile=$PROFILE) ==="
databricks bundle deploy -t "$TARGET" -p "$PROFILE"

echo "=== 2/4 Post-deploy (resources + DB grants + schema) ==="
./scripts/post-deploy.sh "$TARGET" "$PROFILE"

echo "=== 3/4 Starting app ==="
databricks bundle run databricks-vision-app -t "$TARGET" -p "$PROFILE"

echo "=== Deploy complete ==="
