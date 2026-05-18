#!/bin/bash
# post-deploy.sh — Run AFTER `databricks bundle deploy` but BEFORE `databricks bundle run`
#
# 1. Attaches autoscaling Lakebase postgres resource (not yet supported by DABs)
# 2. Grants SP schema privileges on the Lakebase database
# 3. Runs schema migration SQL so tables exist before app starts
# 4. Re-grants SP permissions on the newly-created tables
#
# Lakebase coordinates and OBO-scope toggle are read from `databricks bundle summary`,
# so this script is workspace-agnostic — switching targets is just `-t <target>`.
#
# Usage: ./scripts/post-deploy.sh <target> [profile]

set -euo pipefail

TARGET="${1:?target required (matches a key under \`targets:\` in databricks.yml)}"
PROFILE="${2:-DEFAULT}"
APP_NAME="databricks-vision"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# --- Pull Lakebase config from the bundle summary ---
SUMMARY=$(databricks bundle summary -t "$TARGET" -p "$PROFILE" -o json)
LAKEBASE_ENDPOINT_PATH=$(jq -er '.variables.lakebase_endpoint.value' <<<"$SUMMARY")
LAKEBASE_DATABASE_PATH=$(jq -er '.variables.lakebase_database.value' <<<"$SUMMARY")
DB_HOST=$(jq -er '.variables.lakebase_db_host.value' <<<"$SUMMARY")

# Derive the branch path (everything before /databases/...) for the postgres resource payload.
BRANCH_PATH=$(echo "$LAKEBASE_DATABASE_PATH" | sed 's|/databases/.*||')

echo "  Target: $TARGET"
echo "  Lakebase endpoint: $LAKEBASE_ENDPOINT_PATH"

TOKEN=$(databricks auth token --profile "$PROFILE" 2>&1 | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
HOST=$(databricks auth describe --profile "$PROFILE" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['details']['host'])")

# --- Discover the app's auto-assigned service-principal client id ---
APP_INFO=$(curl -s "$HOST/api/2.0/apps/$APP_NAME" -H "Authorization: Bearer $TOKEN")
SP_CLIENT_ID=$(echo "$APP_INFO" | python3 -c "
import sys, json
d = json.load(sys.stdin)
sp = d.get('service_principal_client_id') or d.get('service_principal_id') or ''
if not sp:
    print('ERROR: app \"' + d.get('name', '?') + '\" has no service_principal_client_id; was the app deployed?', file=sys.stderr)
    sys.exit(1)
print(sp)
")
echo "  App SP client id: $SP_CLIENT_ID"

# --- Step 1: Merge postgres resource into app ---
echo "1/4 Attaching autoscaling Lakebase resource..."

PAYLOAD=$(echo "$APP_INFO" | \
  BRANCH_PATH="$BRANCH_PATH" \
  DATABASE_PATH="$LAKEBASE_DATABASE_PATH" \
  python3 -c "
import sys, json, os

app = json.load(sys.stdin)
resources = app.get('resources', [])

postgres_resource = {
    'name': 'db',
    'postgres': {
        'branch': os.environ['BRANCH_PATH'],
        'database': os.environ['DATABASE_PATH'],
        'permission': 'CAN_CONNECT_AND_CREATE'
    }
}
if not any(r.get('name') == 'db' for r in resources):
    resources.append(postgres_resource)
else:
    resources = [postgres_resource if r.get('name') == 'db' else r for r in resources]

# SP-only auth model — no user_api_scopes wired. All file ops, DB access, and
# model-serving calls go through the app's service principal.
print(json.dumps({'resources': resources}))
")

RESULT=$(curl -s -X PATCH "$HOST/api/2.0/apps/$APP_NAME" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'error_code' in d:
    print(f'ERROR: {d[\"error_code\"]}: {d[\"message\"]}')
    sys.exit(1)
resources = d.get('resources', [])
scopes = d.get('user_api_scopes', [])
print(f'  Resources ({len(resources)}):')
for r in resources:
    name = r.get('name', '?')
    if 'postgres' in r: print(f'    - {name} (postgres/autoscaling)')
    elif 'serving_endpoint' in r: print(f'    - {name} (serving_endpoint: {r[\"serving_endpoint\"][\"name\"]})')
    elif 'job' in r: print(f'    - {name} (job: {r[\"job\"][\"id\"]})')
    else: print(f'    - {name} (unknown)')
print(f'  user_api_scopes: {scopes}')
"

# --- Step 2: Grant SP schema privileges ---
echo "2/4 Granting SP schema privileges on Lakebase..."

cd "$SCRIPT_DIR/../app"

uv run python3 -c "
import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(profile='$PROFILE')
cred = w.postgres.generate_database_credential(endpoint='$LAKEBASE_ENDPOINT_PATH')

conn = psycopg.connect(
    host='$DB_HOST', dbname='databricks_postgres',
    user=w.current_user.me().user_name, password=cred.token,
    port=5432, sslmode='require'
)
conn.autocommit = True
sp = '$SP_CLIENT_ID'
with conn.cursor() as cur:
    cur.execute(f'GRANT ALL ON SCHEMA public TO \"{sp}\"')
    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO \"{sp}\"')
    cur.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO \"{sp}\"')
    cur.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO \"{sp}\"')
conn.close()
print('  Grants applied to SP $SP_CLIENT_ID')
" 2>&1 | grep -v "^warning:"

# --- Step 3: Bootstrap schema (as the user — SP can't CREATE EXTENSION) ---
echo "3/4 Bootstrapping schema (CREATE EXTENSION vector + tables)..."

uv run python3 -c "
import psycopg
from databricks.sdk import WorkspaceClient
from image_gen import _SCHEMA_SQL

w = WorkspaceClient(profile='$PROFILE')
cred = w.postgres.generate_database_credential(endpoint='$LAKEBASE_ENDPOINT_PATH')

conn = psycopg.connect(
    host='$DB_HOST', dbname='databricks_postgres',
    user=w.current_user.me().user_name, password=cred.token,
    port=5432, sslmode='require', autocommit=True,
)
with conn.cursor() as cur:
    cur.execute(_SCHEMA_SQL)
conn.close()
print('  Schema bootstrap complete')
" 2>&1 | grep -v "^warning:"

# --- Step 4: Ensure SP has permissions on the newly-created tables ---
echo "4/4 Ensuring SP table permissions..."

uv run python3 -c "
import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(profile='$PROFILE')
cred = w.postgres.generate_database_credential(endpoint='$LAKEBASE_ENDPOINT_PATH')

conn = psycopg.connect(
    host='$DB_HOST', dbname='databricks_postgres',
    user=w.current_user.me().user_name, password=cred.token,
    port=5432, sslmode='require'
)
conn.autocommit = True
sp = '$SP_CLIENT_ID'
with conn.cursor() as cur:
    cur.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO \"{sp}\"')
    cur.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO \"{sp}\"')
conn.close()
print('  Table permissions ensured')
" 2>&1 | grep -v "^warning:"

echo "Done."
