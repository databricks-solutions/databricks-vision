#!/bin/bash
# build-frontend.sh — Build the app's React UI (src/databricks_vision/ui -> src/databricks_vision/__dist__)
# with Vite via `bun run build` (config: app/vite.config.ts), then verify Tailwind made it into the bundle.
#
# Used by the bundle artifact build (databricks.yml) ahead of `apx build . --skip-ui-build`, and by CI.
#
# CRITICAL: the app uses Tailwind CSS v4 via the @tailwindcss/vite plugin AND @vitejs/plugin-react.
# If Tailwind's plugin is dropped the build still "succeeds" but omits every utility class and the app
# renders unstyled — so this script FAILS when the CSS bundle is suspiciously small.
#
# Usage: ./scripts/build-frontend.sh   (run from anywhere)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../app"

# A full build with Tailwind is ~50 KB of CSS; without it, ~40 KB.
MIN_CSS_BYTES="${MIN_CSS_BYTES:-45000}"

if [ ! -d node_modules ]; then
  echo "Installing frontend dependencies (bun install --frozen-lockfile --ignore-scripts) ..."
  bun install --frozen-lockfile --ignore-scripts
fi

echo "Building frontend (react + tailwind v4) -> src/databricks_vision/__dist__ ..."
bun run build

CSS_BYTES=$(find src/databricks_vision/__dist__/assets -name '*.css' -exec cat {} + | wc -c | tr -d ' ')
if [ "$CSS_BYTES" -lt "$MIN_CSS_BYTES" ]; then
  echo "ERROR: CSS bundle is ${CSS_BYTES} bytes (< ${MIN_CSS_BYTES}) — Tailwind was likely dropped from the build." >&2
  exit 1
fi
echo "  Built. CSS bundle: ${CSS_BYTES} bytes (Tailwind present)."
