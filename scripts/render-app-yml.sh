#!/bin/bash
# render-app-yml.sh — Render app/app.yml from app/app.yml.template using
# bundle variables resolved for the chosen target.
#
# Usage: ./scripts/render-app-yml.sh <target> [profile]

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-DEFAULT}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

SUMMARY=$(databricks bundle summary -t "$TARGET" -p "$PROFILE" -o json)

export LAKEBASE_ENDPOINT=$(jq -er '.variables.lakebase_endpoint.value' <<<"$SUMMARY")
export CATALOG=$(jq -er '.variables.catalog.value' <<<"$SUMMARY")
export SCHEMA_NAME=$(jq -er '.variables.schema_name.value' <<<"$SUMMARY")
export EMBEDDING_ENDPOINT_NAME=$(jq -er '.variables.embedding_endpoint_name.value' <<<"$SUMMARY")

envsubst < app/app.yml.template > app/app.yml
echo "  Rendered app/app.yml for target=$TARGET"
