# Databricks Vision

Production-ready image generation, editing, MLflow-based evaluation, and semantic search on Databricks. One Python library (`image_gen.py`) drives a deployable FastAPI + React Databricks App that supports single-image generate/edit, batch jobs, gallery, MLflow GenAI judge evaluation, semantic search, and bulk import.

<p align="center">
  <img src="samples/collage.png" alt="Sample outputs" width="900" />
</p>

## What it does

- **Generate** images with `gpt-image-2` (auto-routes to `gpt-image-1.5` for transparent backgrounds). Any WxH multiple of 16 up to 3840px, total pixels 655K–8.3M, edge ratio ≤ 3:1.
- **Edit** existing images with prompt + reference. Edits land as new gallery rows.
- **Evaluate** every generated image with **MLflow 3.15 GenAI judges** (`make_judge`, multimodal `{{ trace }}` judges that see the image via `get_span_image`): five 0-5 metric dimensions (quality, prompt, text legibility, safe content, + a user-defined *custom* criterion), each with a per-metric rationale, plus a generated improved-prompt suggestion for weak results. Judge criteria are **editable from the Settings page**; traces + scores land in an MLflow experiment. A structured `databricks-gpt-5-5` call still supplies enrichment (description, tags).
- **Search** the corpus by text or by uploaded image. SigLIP-2 1152-dim embeddings, pgvector HNSW + cosine similarity, single-query join of metadata + similarity. FTS fallback available.
- **Batch generate** via a Databricks Job: multi-image (one prompt template applied to N inputs) or variations (one source × N variation prompts).
- **Import** local images in bulk; the app synthesizes a prompt then runs the same analyzer + embedder pipeline so imported images become searchable.

<p align="center">
  <img src="docs/assets/demo.gif" alt="Databricks Vision demo" width="900" />
</p>

## Stack

- **Backend** — Python, FastAPI, Pydantic
- **Frontend** — React 19, TypeScript, TanStack Router / Query, shadcn/ui, Tailwind
- **Storage** — Unity Catalog Volumes (image bytes + MLflow trace attachments) + Lakebase Autoscaling Postgres with pgvector (metadata, evals, embeddings)
- **Evaluation** — MLflow 3.15 GenAI: `make_judge` multimodal `{{ trace }}` judges on `databricks-gpt-5-5`, traced to an MLflow experiment (UC-Volume artifact location); DB-managed, editable criteria
- **Inference** — Databricks Model Serving wrapping the Responses API with `gpt-image-2` / `gpt-image-1.5`; judge + enrichment backed by `databricks-gpt-5-5`; image + text embeddings from a custom SigLIP-2 SO400M/14-384 endpoint
- **Build / deploy** — Databricks Asset Bundles, [apx](https://github.com/databricks/apx) toolkit, `uv`, `bun`

## Architecture

```
┌────────────────────────────────────┐     ┌────────────────────────────────────┐
│  Databricks App                    │     │  Lakebase Autoscaling Postgres     │
│  (FastAPI + React)                 │◄───►│  (metadata + evals + pgvector,     │
│                                    │     │   editable eval_criteria table)    │
└─────────────┬──────────────────────┘     └────────────────────────────────────┘
              │
              ├──► Foundation Model serving
              │     ├── gpt-image-2 / gpt-image-1.5   (generate, edit)
              │     └── databricks-gpt-5-5            (enrichment + MLflow judges)
              │
              ├──► MLflow 3.15 GenAI evaluation
              │     ├── make_judge {{ trace }} multimodal judges (5 criteria)
              │     │     see the image via the get_span_image tool
              │     └── traces + judge scores  →  MLflow experiment
              │           (attachments stored on a UC Volume)
              │
              ├──► Custom SigLIP-2 SO400M/14-384 endpoint
              │     (text + image  →  1152-dim embeddings)
              │
              └──► Unity Catalog Volumes
                    (PNG bytes + MLflow trace attachments)
                                ▲
   Batch Generation Job ────────┘
   (Databricks Job; ai_query()
    against image-generator endpoint)
```

**Single-image flow:** UI streams partial-image events over SSE while the model generates, then the backend persists bytes to a UC Volume, writes the row to Lakebase, and (as background tasks) scores the image with MLflow judges + computes the SigLIP embedding, then `UPDATE`s the row. Scoring traces the image so the `{{ trace }}` judges can retrieve it via `get_span_image`; judge scores + rationales mirror back into the Lakebase eval columns the gallery reads.

**Batch flow:** the app kicks off a Databricks Job that reads inputs from a UC Volume, runs `ai_query()` against the image-generator serving endpoint, writes outputs back to a Volume, and syncs metadata + embeddings to Lakebase. The gallery shows single-gen and batch images from the same table.

## What's interesting

- **MLflow multimodal judge evaluation** — every generated image is scored by MLflow 3.15 `make_judge` `{{ trace }}` judges that *see* the image (the judge calls the `get_span_image` tool to fetch the image attachment off the trace) and return a 0-5 score + rationale per dimension. Five criteria (quality, prompt, text, safe, + a user-defined custom one) are stored in an editable `eval_criteria` table and manageable from the Settings page; scores + rationales are mirrored into Lakebase for the gallery and logged to an MLflow experiment for history/comparison. See [`app/src/databricks_vision/backend/core/_eval.py`](app/src/databricks_vision/backend/core/_eval.py).
- **Semantic search over the corpus** — every image is embedded with SigLIP-2 (1152-dim) at ingest time and stored in pgvector with an HNSW index on cosine similarity. A single SQL query joins metadata filters with similarity ranking, so the gallery can search by text or by an uploaded image without a separate vector store. See [`ImageSearch` in image_gen.py](image_gen.py).
- **Two-phase persistence** — generate / edit / import endpoints insert the gallery row immediately with placeholder eval fields, then run the analyzer + embedder as background tasks that `UPDATE` the row when ready. The UI polls for a short window after a generate so eval fields appear without manual refresh.
- **Lakebase Autoscaling with OAuth-rotating connections** — the psycopg pool re-fetches a Lakebase credential token on every new connection, with `max_lifetime=2700` so connections recycle before the 1-hour token expiry. See [`VisionWorkspace` in image_gen.py](image_gen.py).
- **`ai_query()` for batch inference** — [`notebooks/02_BATCH_GENERATE.py`](notebooks/02_BATCH_GENERATE.py) calls the image-generator serving endpoint via Spark SQL `ai_query()`, getting per-row parallelism for free.

## Quickstart

Full setup — including Lakebase, UC, and the two bootstrap notebooks — is in **[DEPLOY.md](DEPLOY.md)**. Summary:

1. Provision Lakebase Autoscaling Postgres + a UC catalog/schema/volumes in the target workspace.
2. Run [`notebooks/00_SIGLIP_DEPLOY.py`](notebooks/00_SIGLIP_DEPLOY.py) once (~30 min, GPU endpoint).
3. Run [`notebooks/01_MODEL_DEPLOY.py`](notebooks/01_MODEL_DEPLOY.py) once (~10 min, image-generator pyfunc endpoint).
4. Fill in the `dev` target block in [`databricks.yml`](databricks.yml) with your workspace coordinates.
5. `./scripts/deploy.sh dev <your-profile>`.

Subsequent redeploys take 2–3 minutes.

## Repo layout

```
image_gen.py             # the library — drives the app and any notebook usage
app/                     # FastAPI + React Databricks App
notebooks/               # 00_SIGLIP_DEPLOY, 01_MODEL_DEPLOY, 02_BATCH_GENERATE
scripts/                 # deploy.sh, post-deploy.sh, render-app-yml.sh
databricks.yml           # DAB config; variables-driven, per-target overrides
DEPLOY.md                # full deploy guide
samples/                 # example outputs
```

## Library usage

The same `image_gen.py` the app uses can be driven from a notebook or script:

```python
from image_gen import VisionWorkspace, ImageGen

ws = VisionWorkspace(
    catalog="<your-catalog>",
    schema="<your-schema>",
    lakebase_endpoint="projects/<project>/branches/<branch>/endpoints/<endpoint>",
)
gen = ImageGen(ws)

img = gen.generate(
    prompt="A high-contrast studio photograph of a brushed-aluminium product",
    size="1024x1024",
    quality="high",
)
img.show()
```

See [DEPLOY.md](DEPLOY.md#8-auth-model) for the auth model (service-principal-only today).

## How to get help

Databricks support doesn't cover this content. For questions or bugs, please [open a GitHub issue](https://github.com/databricks-solutions/databricks-vision/issues) and the maintainers will help on a best-effort basis. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

## License

&copy; 2026 Databricks, Inc. All rights reserved. The source in this repository is provided subject to the Databricks License [https://databricks.com/db-license-source]. All included or referenced third-party libraries are subject to the licenses set forth below.

| Library | Description | License | Source |
|---|---|---|---|
| FastAPI | ASGI web framework | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | ASGI server | BSD-3-Clause | https://github.com/encode/uvicorn |
| Pydantic | Data validation | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | Settings management | MIT | https://github.com/pydantic/pydantic-settings |
| sse-starlette | SSE support for Starlette | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| python-multipart | Multipart parsing | Apache-2.0 | https://github.com/Kludex/python-multipart |
| python-dotenv | .env loader | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| httpx | HTTP client | BSD-3-Clause | https://github.com/encode/httpx |
| OpenAI Python SDK | OpenAI client | Apache-2.0 | https://github.com/openai/openai-python |
| MLflow | GenAI evaluation (judges + tracing) | Apache-2.0 | https://github.com/mlflow/mlflow |
| Databricks SDK for Python | Databricks client | Apache-2.0 | https://github.com/databricks/databricks-sdk-py |
| psycopg | PostgreSQL adapter | LGPL-3.0 | https://github.com/psycopg/psycopg |
| pgvector-python | pgvector client | MIT | https://github.com/pgvector/pgvector-python |
| Pillow | Imaging library | MIT-CMU | https://github.com/python-pillow/Pillow |
| matplotlib | Plotting library | PSF-2.0 | https://github.com/matplotlib/matplotlib |
| React | UI library | MIT | https://github.com/facebook/react |
| Vite | Frontend tooling | MIT | https://github.com/vitejs/vite |
| TanStack Router | Type-safe routing | MIT | https://github.com/TanStack/router |
| TanStack Query | Data fetching | MIT | https://github.com/TanStack/query |
| Tailwind CSS | Utility CSS framework | MIT | https://github.com/tailwindlabs/tailwindcss |
| shadcn/ui | Component primitives | MIT | https://github.com/shadcn-ui/ui |
| apx | Databricks Apps toolkit | Databricks License | https://github.com/databricks/apx |
