# shellcheck shell=bash
# _common.sh — sourced by the deploy scripts (not run directly).
#
# Expects TARGET (a key under `targets:` in databricks.yml) and an optional PROFILE argument, then:
#   1. sources deploy/<target>.env if present (gitignored; see deploy/example.env) — the place for
#      DATABRICKS_CONFIG_PROFILE and BUNDLE_VAR_* values that must not be committed;
#   2. exports DATABRICKS_CONFIG_PROFILE when a profile was passed (it wins over the env file);
#   3. otherwise leaves auth to the environment (DATABRICKS_HOST + DATABRICKS_CLIENT_ID +
#      DATABRICKS_AUTH_TYPE=github-oidc in CI), falling back to the DEFAULT profile locally.
# Every `databricks` CLI call and every WorkspaceClient() then resolves the same identity, so
# no step needs a raw token.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENV_FILE="$REPO_ROOT/deploy/${TARGET}.env"
if [ -z "${_VISION_ENV_LOADED:-}" ] && [ -f "$ENV_FILE" ]; then
  echo "  Loading deploy/${TARGET}.env"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
export _VISION_ENV_LOADED=1

if [ -n "${PROFILE:-}" ]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
elif [ -z "${DATABRICKS_CONFIG_PROFILE:-}" ] && [ -z "${DATABRICKS_HOST:-}" ]; then
  export DATABRICKS_CONFIG_PROFILE=DEFAULT
fi

# Mask a value in GitHub Actions logs (they are public for this repo). No-op elsewhere.
mask() {
  if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ -n "${1:-}" ]; then
    echo "::add-mask::$1"
  fi
}

# Run a Python helper with exactly the deps it needs, independent of any project venv.
run_py() {
  uv run --quiet --no-project \
    --with "databricks-sdk>=0.109" \
    --with "psycopg[binary]>=3.2" \
    python3 "$@"
}
