#!/bin/bash
# build-frontend.sh — Rebuild the app's compiled frontend bundle (src/databricks_vision/ui
# -> src/databricks_vision/__dist__) with Vite, without invoking `apx build`.
#
# Why this exists: `apx build` also runs an OpenAPI/orval client-generation step that is broken
# with the current apx toolchain version. When only the React UI changed (and the API client is
# unchanged), this rebuilds just __dist__ so the wheel can be rebuilt with fresh UI assets.
#
# CRITICAL: the app uses Tailwind CSS v4 via the @tailwindcss/vite plugin AND @vitejs/plugin-react.
# Both MUST be in the Vite config or the build silently omits all utility classes (the app renders
# unstyled). This mirrors what apx's own vite config (app/.apx/plugin.ts) sets: root=ui, alias
# @ -> ui, outDir ../__dist__, define __APP_NAME__.
#
# Usage: ./scripts/build-frontend.sh   (run from repo root or scripts/)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../app"

CONFIG="$(mktemp -t vite.vision.XXXXXX.mjs)"
cat > "$CONFIG" <<'EOF'
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";
const APP_UI = "./src/databricks_vision/ui";
export default defineConfig({
  root: APP_UI,
  publicDir: "./public",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": resolve(process.cwd(), APP_UI) } },
  define: { __APP_NAME__: JSON.stringify("databricks-vision") },
  build: { outDir: "../__dist__", emptyOutDir: true },
});
EOF

# vite can't resolve the app's node_modules from a tmp path, so keep the config next to them.
LOCAL_CONFIG="./.vite.build.tmp.mjs"
cp "$CONFIG" "$LOCAL_CONFIG"
trap 'rm -f "$LOCAL_CONFIG" "$CONFIG"' EXIT

echo "Building frontend (react + tailwind v4) -> src/databricks_vision/__dist__ ..."
node_modules/.bin/vite build --config "$LOCAL_CONFIG"

CSS_BYTES=$(find src/databricks_vision/__dist__/assets -name '*.css' -exec wc -c {} + | tail -1 | awk '{print $1}')
echo "  Built. CSS bundle: ${CSS_BYTES} bytes (expect ~50k with Tailwind; ~40k means Tailwind was dropped)."
