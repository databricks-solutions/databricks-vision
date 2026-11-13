# Turning on the CI dev deploy (GitHub OIDC)

`.github/workflows/deploy-dev.yml` deploys the shared dev app (`vision-dev` target) after every check in `ci.yml` passes on a push to `main`. It ends with the same smoke test as a laptop deploy. It is **switched off** until the steps below are done: the job only runs when the repository variable `DEPLOY_DEV_ENABLED` is `true`.

It authenticates with **GitHub OIDC workload identity federation**. GitHub mints a short-lived token for this repo's `dev` environment, and Databricks exchanges it for a service-principal token. No Databricks secret is stored in GitHub. The other environment *secrets* (host, client ID, catalog, Lakebase paths) are not credentials. They are secrets only so that GitHub masks them in this public repo's workflow logs.

Until this is enabled, deploy the dev app from a laptop with `./scripts/deploy.sh vision-dev` (DEPLOY.md §6a). That first laptop deploy also has to happen before step 3 below.

## 1. Create the deploy service principal

In the workspace (Settings → Identity and access → Service principals), create `databricks-vision-ci-<owner>`. FE workspace policy requires the owner's name in service-principal names. Note its **application ID** (a UUID) and its numeric account-level **ID**.

## 2. Federation policy (needs a Databricks *account* admin)

First check how GitHub formats this repo's OIDC subject. Orgs that use immutable subjects produce `repo:<org>@<id>/<repo>@<id>:...`, and the policy must match exactly (wildcards are not supported):

```bash
gh api repos/databricks-solutions/databricks-vision/actions/oidc/customization/sub
```

With the default format (`{"use_default": true}`), the account admin runs:

```bash
databricks account service-principal-federation-policy create <sp-numeric-id> -p <account-profile> --json '{
  "oidc_policy": {
    "issuer": "https://token.actions.githubusercontent.com",
    "audiences": ["<databricks-account-id>"],
    "subject": "repo:databricks-solutions/databricks-vision:environment:dev"
  }
}'
```

Scoping the subject to the `dev` *environment* means only jobs that declare `environment: dev` can obtain the token. Step 4 restricts that environment to `main`.

## 3. Grant the service principal what a deploy touches

After the first laptop deploy, `databricks-vision-dev`, its job and the bundle folder exist. Grant the CI service principal:

| Resource | Grant | Why |
|---|---|---|
| App `databricks-vision-dev` | CAN_MANAGE | redeploy, start, read its SP |
| Job `batch-image-gen-job-dev` | CAN_MANAGE | bundle-managed resource |
| Folder `/Workspace/Shared/.bundle/databricks-vision/vision-dev` | CAN_MANAGE | shared bundle state + synced files |
| Serving endpoints `image-generator`, `siglip2-so400m-embeddings` | CAN_MANAGE | the bundle grants the app SP CAN_QUERY on them |
| MLflow experiment `/Shared/databricks-vision-eval-dev` | CAN_MANAGE | post-deploy grants the app SP CAN_EDIT |
| Lakebase project | CAN_MANAGE | attach the `db` resource, mint DB credentials |
| UC catalog / dev schema | USE CATALOG; USE SCHEMA, CREATE VOLUME, MANAGE on the dev schema | create volumes, grant the app SP |

It also needs a Postgres role on the **dev branch only**, never `production`:

```bash
databricks postgres create-role projects/<project>/branches/dev --role-id <sp-application-id> -p <profile> \
  --json '{"spec": {"identity_type": "SERVICE_PRINCIPAL", "postgres_role": "<sp-application-id>",
           "auth_method": "LAKEBASE_OAUTH_V1", "membership_roles": ["DATABRICKS_SUPERUSER"]}}'
```

The superuser membership is deliberate and limited to the dev branch. The schema bootstrap runs `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, and Postgres requires table ownership for that even when the column already exists. The tables are owned by whoever deployed first.

## 4. GitHub environment + secrets (repo admin)

```bash
R=databricks-solutions/databricks-vision
# Environment restricted to main
gh api -X PUT repos/$R/environments/dev --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
gh api -X POST repos/$R/environments/dev/deployment-branch-policies -f name=main -f type=branch

# Values: the same ones as deploy/vision-dev.env, plus the host and the CI SP's application ID
for k in DATABRICKS_HOST DATABRICKS_CLIENT_ID BUNDLE_VAR_CATALOG BUNDLE_VAR_SCHEMA_NAME \
         BUNDLE_VAR_LAKEBASE_ENDPOINT BUNDLE_VAR_LAKEBASE_BRANCH BUNDLE_VAR_LAKEBASE_DATABASE \
         BUNDLE_VAR_LAKEBASE_DB_HOST; do
  gh secret set "$k" --env dev -R $R    # prompts for the value
done
```

## 5. Network check

GitHub-hosted runners use changing public IPs. If the workspace enforces an IP access list, they will be refused:

```bash
databricks workspace-conf get-status enableIpAccessLists -p <profile>
databricks ip-access-lists list -p <profile>
```

If it is enabled, switch the job to the org's IT-managed runners, which FE workspace allow-lists admit:

```yaml
runs-on:
  group: databricks-solutions-protected-runner-group
  labels: linux-ubuntu-latest
```

## 6. Enable and verify

```bash
gh variable set DEPLOY_DEV_ENABLED --body true -R databricks-solutions/databricks-vision
gh workflow run deploy-dev.yml --ref main -R databricks-solutions/databricks-vision
gh run watch -R databricks-solutions/databricks-vision
```

The run should print `Deploying as <sp-application-id>`, finish with `Smoke test passed.`, and leave the live app untouched. From then on every merge to `main` deploys the dev app automatically.

To switch it off again, run `gh variable delete DEPLOY_DEV_ENABLED -R databricks-solutions/databricks-vision`.
