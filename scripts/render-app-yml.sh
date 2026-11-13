#!/bin/bash
# render-app-yml.sh — Render app/app.yml from app/app.yml.template using
# bundle variables resolved for the chosen target.
#
# Usage: ./scripts/render-app-yml.sh <target> [profile]   (profile: see deploy.sh)

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/_common.sh
source "$SCRIPT_DIR/_common.sh"
cd "$REPO_ROOT"

SUMMARY=$(databricks bundle summary -t "$TARGET" -o json)

# Assign before exporting: `export X=$(...)` would mask a failing jq (missing variable) under set -e.
LAKEBASE_ENDPOINT=$(jq -er '.variables.lakebase_endpoint.value' <<<"$SUMMARY")
CATALOG=$(jq -er '.variables.catalog.value' <<<"$SUMMARY")
SCHEMA_NAME=$(jq -er '.variables.schema_name.value' <<<"$SUMMARY")
EMBEDDING_ENDPOINT_NAME=$(jq -er '.variables.embedding_endpoint_name.value' <<<"$SUMMARY")
EVAL_EXPERIMENT=$(jq -er '.variables.eval_experiment.value' <<<"$SUMMARY")
export LAKEBASE_ENDPOINT CATALOG SCHEMA_NAME EMBEDDING_ENDPOINT_NAME EVAL_EXPERIMENT
mask "$LAKEBASE_ENDPOINT"; mask "$CATALOG"; mask "$SCHEMA_NAME"

envsubst < app/app.yml.template > app/app.yml
echo "  Rendered app/app.yml for target=$TARGET"
