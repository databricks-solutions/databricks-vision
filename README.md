# Databricks Vision

Production-ready image generation, editing, analysis, and semantic search on Databricks. One Python library (`image_gen.py`) drives a deployable FastAPI + React Databricks App that supports single-image generate/edit, batch jobs, gallery, semantic search, and bulk import.

<p align="center">
  <img src="samples/collage.png" alt="Sample outputs" width="900" />
</p>

## What it does

- **Generate** images with `gpt-image-2` (auto-routes to `gpt-image-1.5` for transparent backgrounds). Any WxH multiple of 16 up to 3840px, total pixels 655K–8.3M, edge ratio ≤ 3:1.
- **Edit** existing images with prompt + reference. Edits land as new gallery rows.
- **Analyze** every generated image with `databricks-gpt-5-5`: description, tags, evaluation, 5×0-5 metric sub-scores, missing-elements, safety flags, brand conflicts, an improved-prompt suggestion, and an optional `criteria_evaluation` against user-supplied style guidelines.
- **Search** the corpus by text or by uploaded image. SigLIP-2 1152-dim embeddings, pgvector HNSW + cosine similarity, single-query join of metadata + similarity. FTS fallback available.
- **Batch generate** via a Databricks Job: multi-image (one prompt template applied to N inputs) or variations (one source × N variation prompts).
- **Import** local images in bulk; the app synthesizes a prompt then runs the same analyzer + embedder pipeline so imported images become searchable.

<p align="center">
  <img src="docs/assets/demo.gif" alt="Databricks Vision demo" width="900" />
</p>

## Stack

- **Backend** — Python, FastAPI, Pydantic
- **Frontend** — React 19, TypeScript, TanStack Router / Query, shadcn/ui, Tailwind
- **Storage** — Unity Catalog Volumes (image bytes) + Lakebase Autoscaling Postgres with pgvector (metadata, evals, embeddings)
- **Inference** — Databricks Model Serving wrapping the Responses API with `gpt-image-2` / `gpt-image-1.5`; analyzer backed by `databricks-gpt-5-5`; image + text embeddings from a custom SigLIP-2 SO400M/14-384 endpoint
- **Build / deploy** — Databricks Asset Bundles, [apx](https://github.com/databricks/apx) toolkit, `uv`, `bun`

## Architecture

```
┌────────────────────────────────────┐     ┌────────────────────────────────────┐
│  Databricks App                    │     │  Lakebase Autoscaling Postgres     │
│  (FastAPI + React)                 │◄───►│  (metadata + pgvector embeddings)  │
└─────────────┬──────────────────────┘     └────────────────────────────────────┘
              │
              ├──► Foundation Model serving
              │     ├── gpt-image-2 / gpt-image-1.5   (generate, edit)
              │     └── databricks-gpt-5-5            (analyzer, prompt rewrite)
              │
              ├──► Custom SigLIP-2 SO400M/14-384 endpoint
              │     (text + image  →  1152-dim embeddings)
              │
              └──► Unity Catalog Volumes
                    (PNG bytes, organised by batch / folder)
                                ▲
   Batch Generation Job ────────┘
   (Databricks Job; ai_query()
    against image-generator endpoint)
```

**Single-image flow:** UI streams partial-image events over SSE while the model generates, then the backend persists bytes to a UC Volume, writes the row to Lakebase, and runs the analyzer + embedder as background tasks that `UPDATE` the row when they finish.

**Batch flow:** the app kicks off a Databricks Job that reads inputs from a UC Volume, runs `ai_query()` against the image-generator serving endpoint, writes outputs back to a Volume, and syncs metadata + embeddings to Lakebase. The gallery shows single-gen and batch images from the same table.

## What's interesting

- **Image evaluation** — every generated image is scored on five 0-5 dimensions (quality, prompt adherence, purpose fit, text legibility, safe content) plus categorical safety / brand flags, with a critique paragraph and a suggested improved prompt for off-spec results. See [`ImageAnalyzer` in image_gen.py](image_gen.py).
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
