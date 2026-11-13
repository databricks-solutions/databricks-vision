// Production build config for the React UI (src/databricks_vision/ui -> src/databricks_vision/__dist__).
//
// `apx build` runs `bun run build`, which runs `vite build` with this file. Keep BOTH the react and
// @tailwindcss/vite plugins: without Tailwind's plugin the build silently drops every utility class
// and the app renders unstyled (scripts/build-frontend.sh fails the build if that happens).
//
// apx's dev-server plugin (.apx/plugin.ts) is generated locally and gitignored, so it is not
// imported here; this config only has to produce the static bundle.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const uiRoot = fileURLToPath(new URL("./src/databricks_vision/ui", import.meta.url));

export default defineConfig({
  root: uiRoot,
  publicDir: "./public",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": uiRoot } },
  define: { __APP_NAME__: JSON.stringify("databricks-vision") },
  build: { outDir: "../__dist__", emptyOutDir: true },
});
