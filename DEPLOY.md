# Deploying Databricks Vision

End-to-end guide for deploying the `databricks-vision` app to a Databricks workspace from a clean checkout. Takes ~45 minutes the first time (most of which is GPU endpoint provisioning); subsequent redeploys are 2-3 minutes.

`databricks.yml` ships with a single placeholder target (`dev`). Fill it in for your workspace, or copy the block and rename it if you deploy to multiple workspaces.

---

## 1. Prerequisites

### Workspace
- **Foundation Model serving** enabled (provides `databricks-gpt-5-5` and `gpt-image-2`/`gpt-image-1.5`).
- **Databricks Apps** enabled.
- **GPU model serving** quota (`GPU_SMALL` / A10) for the SigLIP 2 embedding endpoint.
- **Lakebase Autoscaling Postgres** project access (you'll provision the project in step 2a if it doesn't exist).
- **Unity Catalog**: a catalog you can write to, plus the ability to create schemas and volumes inside it.

### Local
- macOS or Linux.
- Python 3.12+.
- [`uv`](https://docs.astral.sh/uv/), [`bun`](https://bun.sh/), and [`apx`](https://github.com/databricks/apx) — the build chain. `apx build .` is invoked by the bundle.
- [`databricks` CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install) v0.230+ (`databricks --version`).
- `jq` and `envsubst` (from GNU `gettext`).
  - macOS: `brew install jq gettext`, then either `brew link --force gettext` or `export PATH="$(brew --prefix gettext)/bin:$PATH"` — `gettext` is keg-only and isn't symlinked by default.
- A configured Databricks CLI profile pointing at the target workspace (`databricks auth login --host https://<workspace>.cloud.databricks.com`).

`deploy.sh` resolves Python dependencies via [public PyPI](https://pypi.org) by default. If you're on a network where `pypi.org` is blocked, export `UV_INDEX_URL=<your-mirror>` before running.

---

## 2. One-time workspace bootstrap

Skip any step that's already done.

### 2a. Provision Lakebase Autoscaling Postgres

In the Databricks UI: *Compute → Lakebase → Autoscaling*.

1. Create a project (any name; you'll reference it by resource path).
2. Create a branch (or use the default `production`).
3. A `databricks_postgres` database is created automatically under the branch — you don't need to create one manually.
4. On the branch detail page, capture the **endpoint hostname** (looks like `ep-<slug>.database.<region>.cloud.databricks.com`) from the connection-details panel.
5. Get the database **resource path** via the CLI:
   ```bash
   databricks postgres list-databases projects/<project>/branches/<branch> -p <profile> -o json | jq -r '.[].name'
   ```
   Newer Lakebase uses the human-readable ID (e.g. `databricks-postgres` — with hyphen). Older instances use a generated UID like `db-<8>-<11>`.

You now have everything you need for the four `lakebase_*` variables in step 3.

### 2b. Create the UC catalog, schema, and volumes

```sql
CREATE CATALOG IF NOT EXISTS <catalog>;
CREATE SCHEMA  IF NOT EXISTS <catalog>.<schema>;
CREATE VOLUME  IF NOT EXISTS <catalog>.<schema>.generated_images;
CREATE VOLUME  IF NOT EXISTS <catalog>.<schema>.vision_images;
```

The volume names are fixed; only catalog/schema vary.

### 2c. Edit `notebooks/config.py`

Both bootstrap notebooks read `CATALOG` and `SCHEMA` from `notebooks/config.py`. Open it and replace the placeholders with the catalog/schema you created in step 2b:

```python
CATALOG = "<your-catalog>"
SCHEMA  = "<your-schema>"
```

### 2d. Deploy the SigLIP 2 embedding endpoint

In the workspace UI, open `notebooks/00_SIGLIP_DEPLOY.py`. Only two widgets, both with sensible defaults:

| Widget          | Value                                                                           |
| --------------- | ------------------------------------------------------------------------------- |
| `endpoint_name` | `siglip2-so400m-embeddings` (default; change only on a name collision)          |
| `hf_model_id`   | `google/siglip2-so400m-patch14-384` (default)                                   |

Run all cells. ~30 minutes for the GPU endpoint to provision. Idempotent on re-run.

### 2e. Deploy the image-generator pyfunc endpoint

Open `notebooks/01_MODEL_DEPLOY.py` and run all cells. ~10 minutes to register the model and deploy the `image-generator` endpoint.

The notebook includes a **local smoke-test cell** that builds an inline 256×256 PNG and calls `model.predict` once. This burns a single image-generation API call but exercises the full edit-mode code path before the (slower) endpoint deploy. Skip the smoke-test cells if you'd rather not pay for that one call — the signature is defined declaratively and the deploy works without them.

---

## 3. Add a target to `databricks.yml`

Open [`databricks.yml`](databricks.yml). Replace the `<...>` placeholders in the `dev` target block with your workspace's values:

```yaml
  dev:
    mode: development
    workspace:
      host: https://<your-workspace>.cloud.databricks.com
    variables:
      catalog: <your-catalog>
      schema_name: <your-schema>
      lakebase_endpoint: projects/<project>/branches/<branch>/endpoints/<endpoint>
      lakebase_branch:   projects/<project>/branches/<branch>
      lakebase_database: projects/<project>/branches/<branch>/databases/<db-id>
      lakebase_db_host:  ep-<slug>.database.<region>.cloud.databricks.com
```

Rename `dev` to whatever target name you want (used as the first arg to `deploy.sh`). Copy the block if you deploy to multiple workspaces.

Verify with:

```bash
databricks bundle summary -t <your-target> -p <your-profile> | head -10
```

The `Host:` line should match your workspace URL.

---

## 4. First deploy

```bash
./scripts/deploy.sh <your-target> <your-profile>
```

The script chains four steps:

1. **`render-app-yml.sh`** reads bundle variables via `databricks bundle summary` and renders `app/app.yml` from `app/app.yml.template` (the rendered `app.yml` is gitignored).
2. **`databricks bundle deploy -t <target>`** builds the React app, uploads it, and creates four app resources: `image-gen-endpoint`, `siglip-embedding-endpoint`, `batch-gen-job`, `db`.
3. **`post-deploy.sh`** PATCHes the Lakebase `db` resource as a safety net (the YAML declaration is the primary mechanism), grants the SP schema-level Postgres privileges, bootstraps the schema, and grants table-level privileges.
4. **`databricks bundle run databricks-vision-app -t <target>`** starts the app. First start takes ~2 minutes.

Expect the app process to log Volume 403s after step 4 finishes — that's normal, fixed in the next step.

---

## 5. Grant the app's service principal access to UC

The app's SP is auto-created during the first deploy. Find its client ID:

```bash
databricks apps get databricks-vision -p <your-profile> -o json | jq -r '.service_principal_client_id'
```

Then in a SQL editor:

```sql
GRANT USE_CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
GRANT USE_SCHEMA  ON SCHEMA  <catalog>.<schema> TO `<sp-client-id>`;
GRANT READ_VOLUME, WRITE_VOLUME ON VOLUME <catalog>.<schema>.generated_images TO `<sp-client-id>`;
GRANT READ_VOLUME, WRITE_VOLUME ON VOLUME <catalog>.<schema>.vision_images   TO `<sp-client-id>`;
```

(Postgres-side schema privileges were already applied by `post-deploy.sh`; no separate Postgres `GRANT` needed.)

UC grants take effect immediately — no redeploy needed. Open the app URL (printed by `bundle run`) and try a single image generation. If the first request still 403s, restart the app from the Apps UI to clear cached error state.

---

## 6. Subsequent redeploys

```bash
./scripts/deploy.sh <your-target> <your-profile>
```

The bundle handles incremental sync; only changed files are uploaded. If you edited `_SCHEMA_SQL` in `image_gen.py`, see *Troubleshooting → stale schema bootstrap*.

---

## 7. Coworker access

The app runs everything data-plane as the SP, so coworkers only need workspace-level "Can Use" on the app:

1. Create a group in the workspace UI (e.g. `vision-app-users`).
2. *Compute → Apps → databricks-vision → Permissions* → add the group with **Can Use**.

No additional UC, Volume, or serving-endpoint grants needed for users.

---

## 8. Auth model

The app runs service-principal-only. Both file operations (UC Volumes via `ws.files.*`) and model serving calls (`/serving-endpoints/...`) use the app's auto-generated service principal regardless of any `X-Forwarded-Access-Token` header.

This is the right architecture for the shared-gallery use case: every co-worker sees the same generated images regardless of their individual Unity Catalog grants. User attribution still works via the `X-Forwarded-Email` header for `created_by` stamping.

To switch to per-user OBO for OpenAI / Responses calls, edit `_get_user_token` in [`app/src/databricks_vision/backend/core/_image_gen_dep.py`](app/src/databricks_vision/backend/core/_image_gen_dep.py).

---

## 9. Troubleshooting

### `envsubst: command not found` during step 0
macOS only. `brew install gettext` installs it but doesn't symlink it. Run `brew link --force gettext` or `export PATH="$(brew --prefix gettext)/bin:$PATH"`.

### `bundle deploy` fails on `siglip-embedding-endpoint` permission grant
The endpoint doesn't exist yet. Finish step 2c first.

### App container starts but every Volume read returns 403
SP doesn't have UC grants yet. Apply step 5.

### App container fails to start with `permission denied for schema public`
`post-deploy.sh` didn't run or failed midway. Re-run `./scripts/deploy.sh`; the script is idempotent.

### Stale schema bootstrap (new columns silently no-op)
`post-deploy.sh` imports `_SCHEMA_SQL` from the app's local `.venv`, which holds a hatch-built **copy** of `image_gen.py`. After local edits to `image_gen.py`, the venv copy can go stale. Fix:

```bash
rm app/.venv/lib/python*/site-packages/image_gen.py
./scripts/deploy.sh <target> <profile>
```

### Lakebase `db` resource missing after deploy
Update `databricks` CLI to v0.230+ (older versions ignore the YAML `postgres:` AppResource). `post-deploy.sh`'s PATCH safety net should also recover it.

### `databricks bundle summary` errors with "variable not set"
You added a target but forgot one of the per-workspace variables. Compare to the placeholder block in `databricks.yml`.

### Where to file platform issues
If you hit a Databricks platform issue (Apps, DABs, Lakebase, Foundation Model serving) while deploying or running the app, open a Databricks support ticket against your workspace.
