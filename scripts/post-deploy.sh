#!/bin/bash
# post-deploy.sh — Run AFTER `databricks bundle deploy` but BEFORE `databricks bundle run`.
#
# 1. Attaches the autoscaling Lakebase postgres resource (safety net for older bundle versions)
# 2. Lakebase: grants the app SP schema privileges, bootstraps the schema as the deployer
#    (the SP can't CREATE EXTENSION), then re-grants on the new tables
# 3. Unity Catalog: creates the app's volumes if missing and grants the app SP
#    USE CATALOG / USE SCHEMA / READ+WRITE VOLUME (DEPLOY.md step 5, automated)
# 4. MLflow: ensures the eval experiment exists with a UC Volume artifact store + SP CAN_EDIT
#
# Every value comes from `databricks bundle summary` for the target, so the script is
# workspace-agnostic. Auth comes from the profile / environment (see scripts/_common.sh); no step
# handles a raw token. Idempotent: safe to re-run.
#
# Usage: ./scripts/post-deploy.sh <target> [profile]

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/_common.sh
source "$SCRIPT_DIR/_common.sh"
cd "$REPO_ROOT"

# --- Resolve the target's config from the bundle summary ---
SUMMARY=$(databricks bundle summary -t "$TARGET" -o json)
APP_NAME=$(jq -er '.resources.apps["databricks-vision-app"].name' <<<"$SUMMARY")
LAKEBASE_ENDPOINT_PATH=$(jq -er '.variables.lakebase_endpoint.value' <<<"$SUMMARY")
LAKEBASE_DATABASE_PATH=$(jq -er '.variables.lakebase_database.value' <<<"$SUMMARY")
DB_HOST=$(jq -er '.variables.lakebase_db_host.value' <<<"$SUMMARY")
EVAL_EXPERIMENT=$(jq -er '.variables.eval_experiment.value' <<<"$SUMMARY")
CATALOG=$(jq -er '.variables.catalog.value' <<<"$SUMMARY")
SCHEMA_NAME=$(jq -er '.variables.schema_name.value' <<<"$SUMMARY")
# Branch path (everything before /databases/...) for the postgres resource payload.
BRANCH_PATH="${LAKEBASE_DATABASE_PATH%%/databases/*}"
mask "$LAKEBASE_ENDPOINT_PATH"; mask "$LAKEBASE_DATABASE_PATH"; mask "$BRANCH_PATH"; mask "$DB_HOST"
mask "$CATALOG"; mask "$SCHEMA_NAME"

echo "  Target: $TARGET   App: $APP_NAME"
echo "  Lakebase endpoint: $LAKEBASE_ENDPOINT_PATH"

# --- Discover the app's auto-assigned service principal ---
APP_INFO=$(databricks api get "/api/2.0/apps/$APP_NAME")
SP_CLIENT_ID=$(jq -r '.service_principal_client_id // .service_principal_id // empty' <<<"$APP_INFO")
if [ -z "$SP_CLIENT_ID" ]; then
  echo "ERROR: app \"$APP_NAME\" has no service_principal_client_id; was the app deployed?" >&2
  exit 1
fi
mask "$SP_CLIENT_ID"
mask "$(jq -r '.url // empty' <<<"$APP_INFO")"
echo "  App SP client id: $SP_CLIENT_ID"

# --- 1. Merge the postgres resource into the app (idempotent) ---
echo "1/4 Attaching autoscaling Lakebase resource..."
# SP-only auth model: no user_api_scopes are wired (file ops, DB and model serving use the app SP).
PAYLOAD=$(jq -c --arg branch "$BRANCH_PATH" --arg db "$LAKEBASE_DATABASE_PATH" '
  {name: "db", postgres: {branch: $branch, database: $db, permission: "CAN_CONNECT_AND_CREATE"}} as $res
  | (.resources // []) as $r
  | {resources: (if any($r[]; .name == "db") then $r | map(if .name == "db" then $res else . end)
                 else $r + [$res] end)}' <<<"$APP_INFO")
RESULT=$(databricks api patch "/api/2.0/apps/$APP_NAME" --json "$PAYLOAD")
jq -r '"  Resources (\(.resources | length)):",
       (.resources[] | "    - \(.name) (" + (
          if .postgres then "postgres/autoscaling"
          elif .serving_endpoint then "serving_endpoint: \(.serving_endpoint.name)"
          elif .job then "job"
          else "other" end) + ")")' <<<"$RESULT"

# --- 2. Lakebase: grants + schema bootstrap ---
echo "2/4 Lakebase grants + schema bootstrap..."
run_py scripts/deploy_helpers.py lakebase-bootstrap \
  --endpoint "$LAKEBASE_ENDPOINT_PATH" --host "$DB_HOST" --sp "$SP_CLIENT_ID"

# --- 3. Unity Catalog: app volumes + grants ---
echo "3/4 Unity Catalog volumes + grants..."
run_py scripts/deploy_helpers.py uc-grants \
  --catalog "$CATALOG" --schema "$SCHEMA_NAME" --sp "$SP_CLIENT_ID" \
  --volume generated_images --volume vision_images --volume mlflow_traces

# --- 4. MLflow eval experiment (non-fatal: the app falls back to plain analysis without it) ---
# MLflow uploads trace *attachments* to the experiment's artifact store. The default store is the
# regional blob proxy, which serverless/Apps compute can't reach, so the experiment is created with
# artifact_location on a UC Volume the app SP can write to. Ref: FEVM-391.
echo "4/4 MLflow eval experiment..."
run_py scripts/deploy_helpers.py mlflow-experiment \
  --name "$EVAL_EXPERIMENT" --sp "$SP_CLIENT_ID" \
  --artifact-location "dbfs:/Volumes/${CATALOG}/${SCHEMA_NAME}/mlflow_traces/${APP_NAME}" \
  || echo "  WARN: MLflow experiment setup failed — the app will run without MLflow evaluation."

echo "Done."
