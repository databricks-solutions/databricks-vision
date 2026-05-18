"""Async image generation, editing, analysis, and search via Databricks + OpenAI Responses API.

Architecture:
  VisionWorkspace  — single auth handle (WorkspaceClient + AsyncOpenAI + Lakebase pool + SigLIP)
  ImageGen         — generate / edit / rewrite / commit / show
  ImageAnalyzer    — Pydantic-structured image evaluation
  ImageSearch      — pgvector text→image and image→image similarity over committed images
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import psycopg
from databricks.sdk import WorkspaceClient
from openai import AsyncOpenAI
from pgvector.psycopg import register_vector
from PIL import Image as PILImage
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 1152

MODEL_PRESETS = {
    "gpt-image-1.5": {
        "defaults": {"quality": "auto", "size": "1536x1024", "partial_images": 3},
        "supports_transparent": True,
        "supports_input_fidelity": True,
    },
    "gpt-image-2": {
        # size accepts any resolution satisfying the gpt-image-2 constraints
        # (multiples of 16, max edge 3840px, ratio ≤ 3:1, 655,360–8,294,400 total pixels).
        # Popular: 1024x1024, 1536x1024, 1024x1536, 2048x2048, 2048x1152, 3840x2160, 2160x3840.
        "defaults": {"quality": "auto", "size": "auto", "partial_images": 3},
        "supports_transparent": False,
        "supports_input_fidelity": False,
    },
}

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- batch_runs: tracks both multi-image batch jobs and single-gen pseudo-batches
CREATE TABLE IF NOT EXISTS batch_runs (
    batch_id            VARCHAR(8) PRIMARY KEY,
    batch_name          VARCHAR(255) DEFAULT '',
    batch_mode          VARCHAR(20) NOT NULL DEFAULT 'multi_image',
    input_volume_path   TEXT NOT NULL DEFAULT '',
    source_image_path   TEXT DEFAULT '',
    reference_image_path TEXT DEFAULT '',
    prompt_template     TEXT NOT NULL DEFAULT '',
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          VARCHAR(255),
    job_run_id          BIGINT,
    total_images        INTEGER,
    successful_images   INTEGER,
    output_volume_path  TEXT,
    folder              VARCHAR(255) DEFAULT 'default'
);

-- generated_images: every image produced by the lib or app lands here
CREATE TABLE IF NOT EXISTS generated_images (
    id              INTEGER NOT NULL,
    batch_id        VARCHAR(8) NOT NULL REFERENCES batch_runs(batch_id) ON DELETE CASCADE,
    image_name      VARCHAR(255),
    prompt          TEXT,
    status          VARCHAR(20),
    error_message   TEXT,
    volume_path     TEXT,
    variation_label VARCHAR(255) DEFAULT '',
    input_image_path TEXT DEFAULT '',
    description     TEXT,
    tags            JSONB DEFAULT '[]',
    evaluation      TEXT,
    metrics         JSONB,
    missing_elements JSONB DEFAULT '[]',
    safety_flags    JSONB DEFAULT '[]',
    brand_conflicts JSONB DEFAULT '[]',
    improved_prompt TEXT,
    thumbnail_path  TEXT,
    image_model     VARCHAR(64),
    size            VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criteria_evaluation TEXT,
    embedding       VECTOR(1152),
    PRIMARY KEY (batch_id, id)
);

CREATE TABLE IF NOT EXISTS image_versions (
    version_id      SERIAL PRIMARY KEY,
    batch_id        VARCHAR(8) NOT NULL,
    image_id        INTEGER NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    prompt          TEXT NOT NULL,
    status          VARCHAR(20),
    error_message   TEXT,
    volume_path     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (batch_id, image_id) REFERENCES generated_images(batch_id, id) ON DELETE CASCADE,
    UNIQUE (batch_id, image_id, version)
);

CREATE TABLE IF NOT EXISTS folders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO folders (name) VALUES ('default') ON CONFLICT DO NOTHING;

-- Style guidelines: named, reusable analyzer criteria (brand voice, do/don't, etc.)
-- Picked from a dropdown on the generate form; body is sent to the analyzer as `criteria`.
CREATE TABLE IF NOT EXISTS style_guidelines (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- At most one row may carry is_default=TRUE (partial unique index).
CREATE UNIQUE INDEX IF NOT EXISTS idx_style_guidelines_one_default
    ON style_guidelines (is_default) WHERE is_default;

-- Smart Compose: cached composition recipes
CREATE TABLE IF NOT EXISTS recipes (
    recipe_id       VARCHAR(8) PRIMARY KEY,
    recipe_name     VARCHAR(255) NOT NULL,
    template_path   TEXT,
    description     TEXT,
    parameters      JSONB NOT NULL DEFAULT '[]',
    code            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(255)
);

-- Migrations: add new columns to existing tables (idempotent).
-- ADD COLUMN IF NOT EXISTS is Postgres 9.6+; we prefer it over the DO/PL-pgSQL guard
-- because the guarded form silently skipped on at least one Lakebase endpoint and we
-- couldn't tell from the logs.
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS thumbnail_path TEXT;
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS image_model VARCHAR(64);
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS size VARCHAR(20);
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS criteria_evaluation TEXT;
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS embedding VECTOR(1152);
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS evaluation TEXT;
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS metrics JSONB;
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS missing_elements JSONB DEFAULT '[]';
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS safety_flags JSONB DEFAULT '[]';
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS brand_conflicts JSONB DEFAULT '[]';
ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS improved_prompt TEXT;
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS folder VARCHAR(255) DEFAULT 'default';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS size VARCHAR(20) DEFAULT '1024x1024';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS quality VARCHAR(20) DEFAULT 'low';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS image_model VARCHAR(40) DEFAULT 'gpt-image-2';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS output_format VARCHAR(20) DEFAULT 'png';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS background VARCHAR(20) DEFAULT 'opaque';
ALTER TABLE batch_runs ADD COLUMN IF NOT EXISTS style_guideline_id INTEGER;

-- Indexes (created last so they reference columns added via ALTER above)
CREATE INDEX IF NOT EXISTS idx_generated_images_fts
    ON generated_images
    USING GIN (to_tsvector('english',
        coalesce(prompt, '') || ' ' ||
        coalesce(image_name, '') || ' ' ||
        coalesce(variation_label, '') || ' ' ||
        coalesce(description, '')
    ));

CREATE INDEX IF NOT EXISTS idx_generated_images_embedding_hnsw
    ON generated_images USING hnsw (embedding vector_cosine_ops);
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GeneratedImage:
    """An image produced by `ImageGen.generate` or `.edit`. Already persisted to UC Volume
    and Lakebase by the time the caller sees it (save+analyze+embed are part of generate)."""

    bytes: bytes
    prompt: str
    image_model: str
    size: str | None = None
    batch_id: str | None = None
    id: int | None = None
    storage_path: str | None = None
    analysis: "ImageAnalysis | None" = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GenerateEvent:
    """Event emitted while streaming images from `ImageGen.stream_generate` / `stream_edit`.

    Types:
      - "partial":    a partial frame for image *index*; `bytes_b64` carries the bytes.
      - "image_done": the final image bytes have arrived; `bytes_b64` is the full image.
                      Persistence (Volume write + analyze + embed + DB insert) starts after.
      - "saved":      persistence complete for image *index*; `image` carries the persisted
                      `GeneratedImage` (with id, storage_path, analysis populated).
      - "error":      something went wrong for image *index*; `error` carries the message.
    """

    type: str
    index: int
    bytes_b64: str | None = None
    image: "GeneratedImage | None" = None
    error: str | None = None


@dataclass
class SearchResult:
    """One row from `ImageSearch`. Image bytes are loaded lazily on `.bytes()`."""

    batch_id: str
    id: int
    storage_path: str
    prompt: str
    description: str | None
    similarity: float
    _workspace: "VisionWorkspace"

    def bytes(self) -> bytes:
        return self._workspace.read_bytes(self.storage_path)


# ---------------------------------------------------------------------------
# Pydantic models for analysis
# ---------------------------------------------------------------------------


class ImageMetrics(BaseModel):
    """Five 0-5 sub-scores. 5 = excellent, 0 = unusable. The model should be willing to
    give 5s when warranted — these are sanity ratings, not graded curves.
    """

    quality: int = Field(ge=0, le=5, description="Overall visual / technical quality")
    prompt_adherence: int = Field(ge=0, le=5, description="Every element of the prompt is visible and correct")
    purpose_fit: int = Field(ge=0, le=5, description="Suitability for the stated purpose; 3 if no purpose given")
    text_legibility: int = Field(ge=0, le=5, description="Clarity / correctness of in-image text; 5 if no text required")
    safe_content: int = Field(ge=0, le=5, description="5 = fully safe, 0 = clearly problematic. Not affected by brand conflicts.")


class ImageAnalysis(BaseModel):
    """Structured evaluation of a generated image.

    Combines the denormalised `description` + `tags` (used for FTS and badges) with the
    rich evaluation fields (paragraph + 5 sub-score `metrics` + issue lists + improved
    prompt suggestion). `criteria_evaluation` is filled only when the caller passes
    user-supplied evaluation criteria (e.g., brand or style guidelines).

    Field names are aligned with the FE wire shape:
    metrics / missing_or_wrong_elements / safety_flags / brand_conflicts / improved_prompt.
    The DB column for missing_or_wrong_elements is `missing_elements` — the rename happens
    at the SQL boundary, not on the Pydantic model.
    """

    description: str = Field(description="1-2 sentence factual description of what's in the image")
    tags: list[str] = Field(description="5-10 short relevant tags / keywords (subject, style, palette, mood)")
    evaluation: str = Field(description="Critical review against prompt, purpose and common criteria (composition, lighting, realism, brand fit, text)")
    metrics: ImageMetrics = Field(description="Five 0-5 sub-scores")
    missing_or_wrong_elements: list[str] = Field(default_factory=list, description="Prompt elements not visible, incorrect, or with illegible / misspelled text")
    safety_flags: list[str] = Field(default_factory=list, description="Genuine safety issues only: NSFW, graphic content, harmful stereotypes. Do NOT list brand / competitor issues here.")
    brand_conflicts: list[str] = Field(default_factory=list, description="Visible competitor products or elements conflicting with the given brand. Empty list if no brand was provided or no conflicts found.")
    improved_prompt: str | None = Field(default=None, description="Revised prompt if the image has real issues (including brand conflicts); null if already good")
    criteria_evaluation: str | None = Field(
        default=None,
        description="Evaluation against user-supplied criteria; null when no criteria provided",
    )


ANALYZER_SYSTEM_PROMPT = """Analyze an AI-generated image. The user will provide the image and
optionally the original generation prompt and / or evaluation criteria (brand or style
guidelines). Produce a structured response:

- description: a 1-2 sentence factual description of what's in the image.
- tags: 5-10 short relevant keywords (subject, style, palette, mood) — short lowercase phrases.
- evaluation: a paragraph evaluating the image against criteria appropriate to the context —
  composition, lighting, realism, prompt adherence, purpose fit, text correctness, brand cues.
  Be specific and honest; call out both strengths and weaknesses.
- metrics: 0-5 sub-scores across quality, prompt_adherence, purpose_fit, text_legibility,
  safe_content. Use the full range; reserve 5 for genuinely excellent.
- missing_or_wrong_elements: prompt elements not visible, incorrect, or with illegible /
  misspelled text. Empty list if nothing is missing.
- safety_flags: only genuine safety issues (NSFW, graphic content, harmful stereotypes).
  Brand conflicts do NOT belong here.
- brand_conflicts: visible competitor products / elements conflicting with the given brand.
  Empty list if no brand was provided or no conflicts found.
- improved_prompt: a revised prompt that fixes any real issues (including brand conflicts).
  Null if the image is already good.

If the user supplied evaluation criteria, also fill criteria_evaluation with a concise
paragraph stating how well the image meets them and calling out specific issues. If no
criteria were provided, leave criteria_evaluation null."""


# ---------------------------------------------------------------------------
# VisionWorkspace — single auth handle
# ---------------------------------------------------------------------------


class VisionWorkspace:
    """Single auth handle: WorkspaceClient + OpenAI client + Lakebase pool + SigLIP embeddings.

    ```python
    vw = VisionWorkspace(
        host=os.environ["DATABRICKS_HOST"],
        token=os.environ["DATABRICKS_TOKEN"],
        lakebase_project="image-gen-dbx",   # display name of the autoscaling Postgres project
    )
    ```

    All four Databricks capabilities — Volumes, model serving (Responses API + SigLIP),
    Postgres credential generation — go through `self.w` so there is one source of auth.
    """

    def __init__(
        self,
        host: str | None = None,
        token: str | None = None,
        lakebase_project: str | None = None,
        lakebase_branch_id: str | None = None,
        lakebase_database: str = "databricks_postgres",
        embedding_endpoint: str = "siglip2-so400m-embeddings",
        client: WorkspaceClient | None = None,
        pool: ConnectionPool | None = None,
    ):
        """
        Args:
            host, token: Databricks workspace credentials. Falls back to env (DATABRICKS_HOST/TOKEN)
                or the standard SDK auth chain. Ignored if `client` is provided.
            lakebase_project: display name of the Lakebase autoscaling project (e.g. "image-gen-dbx").
                Required to use commit/search; can be omitted for local-only ImageGen use.
            lakebase_branch_id: optional branch slug (e.g. "br-frosty-pond-d2a217ig"); if None, the
                default branch in the project is used.
            lakebase_database: Postgres DB name within the branch (default "databricks_postgres").
            embedding_endpoint: name of the SigLIP serving endpoint.
            client: pre-built WorkspaceClient to reuse (e.g. the service-principal client owned by a
                Databricks App). When supplied, `host`/`token` are ignored and `self.w` becomes this
                instance. Use `openai_for_token` to mint per-request OBO OpenAI clients on top.
            pool: pre-built psycopg ConnectionPool to reuse (e.g. the app's existing Lakebase pool).
                When supplied, the workspace skips its own _open_pool flow. The caller is responsible
                for ensuring `register_vector(conn)` runs on each connection (the lib does this in
                its own pool's `configure` callback).
        """
        if client is not None:
            self.w = client
        else:
            self.w = WorkspaceClient(host=host, token=token) if (host or token) else WorkspaceClient()
        self.lakebase_project = lakebase_project
        self.lakebase_branch_id = lakebase_branch_id
        self.lakebase_database = lakebase_database
        self.embedding_endpoint = embedding_endpoint

        self._openai: AsyncOpenAI | None = None
        self._pool: ConnectionPool | None = pool
        self._endpoint_path: str | None = None

    # -- lazy clients ---------------------------------------------------------

    @property
    def openai(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = AsyncOpenAI(
                base_url=f"{self.w.config.host}/serving-endpoints",
                api_key=self.w.config.token,
            )
        return self._openai

    def openai_for_token(self, obo_token: str) -> AsyncOpenAI:
        """Mint a per-request `AsyncOpenAI` client authenticated as the calling user.

        Used inside Databricks Apps where each HTTP request carries a user OBO token in
        `X-Forwarded-Access-Token`. Lakebase pool and SigLIP serving calls keep using
        `self.w` (the service-principal client) — only OpenAI/Responses goes through the
        user identity, so per-user model-serving permissions and quotas apply.
        """
        return AsyncOpenAI(
            base_url=f"{self.w.config.host}/serving-endpoints",
            api_key=obo_token,
        )

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            if not self.lakebase_project:
                raise RuntimeError(
                    "VisionWorkspace was initialized without `lakebase_project` — "
                    "DB-backed features (commit, search) are unavailable."
                )
            self._pool = self._open_pool()
        return self._pool

    def _open_pool(self) -> ConnectionPool:
        endpoint_path, host = self._resolve_endpoint()
        self._endpoint_path = endpoint_path
        user = self.w.current_user.me().user_name
        port = os.environ.get("PGPORT", "5432")
        ws = self.w

        def fresh_token() -> str:
            return ws.postgres.generate_database_credential(endpoint=endpoint_path).token

        conninfo = f"dbname={self.lakebase_database} user={user} host={host} port={port} sslmode=require"

        # Bootstrap: install the vector extension + schema BEFORE opening the pool, so the
        # per-connection `register_vector` callback can find the type on every subsequent connect.
        with psycopg.connect(conninfo, password=fresh_token(), autocommit=True) as boot:
            boot.execute(_SCHEMA_SQL)

        class OAuthConnection(psycopg.Connection):
            @classmethod
            def connect(cls, conninfo: str = "", **kwargs):
                kwargs["password"] = fresh_token()
                return super().connect(conninfo, **kwargs)

        def configure(conn: psycopg.Connection) -> None:
            register_vector(conn)

        pool = ConnectionPool(
            conninfo=conninfo,
            connection_class=OAuthConnection,
            configure=configure,
            min_size=1,
            max_size=4,
            max_lifetime=2700,  # recycle before 1-hour token expiry
            kwargs={"row_factory": dict_row},
            open=True,
        )
        return pool

    def _resolve_endpoint(self) -> tuple[str, str]:
        """Resolve (endpoint_resource_path, host) for the configured project + branch.

        Walks the autoscaling Postgres hierarchy: project (by display name) → default branch
        (or override) → first endpoint.
        """
        projects = list(self.w.postgres.list_projects())
        project = next(
            (
                p for p in projects
                if (p.status and p.status.display_name == self.lakebase_project)
                or (p.spec and p.spec.display_name == self.lakebase_project)
            ),
            None,
        )
        if project is None:
            available = [
                (p.status.display_name if p.status else p.spec.display_name)
                for p in projects if (p.status or p.spec)
            ]
            raise RuntimeError(
                f"Lakebase project {self.lakebase_project!r} not found. Available: {available}"
            )

        branches = list(self.w.postgres.list_branches(parent=project.name))
        if not branches:
            raise RuntimeError(f"Project {self.lakebase_project!r} has no branches.")

        if self.lakebase_branch_id:
            suffix = f"/branches/{self.lakebase_branch_id}"
            branch = next((b for b in branches if b.name.endswith(suffix)), None)
            if branch is None:
                raise RuntimeError(
                    f"Branch id {self.lakebase_branch_id!r} not found in {self.lakebase_project!r}."
                )
        else:
            branch = next(
                (b for b in branches if b.status and b.status.default),
                branches[0],
            )

        endpoints = list(self.w.postgres.list_endpoints(parent=branch.name))
        if not endpoints:
            raise RuntimeError(f"Branch {branch.name!r} has no endpoints.")
        endpoint = endpoints[0]

        host = (
            endpoint.status.hosts.host
            if endpoint.status and endpoint.status.hosts
            else None
        )
        if not host:
            raise RuntimeError(f"Endpoint {endpoint.name!r} has no resolved host yet.")
        return endpoint.name, host

    # -- I/O ------------------------------------------------------------------

    @staticmethod
    def is_volume_path(path: str) -> bool:
        return path.startswith("/Volumes/")

    def write_bytes(self, path: str, data: bytes) -> None:
        if self.is_volume_path(path):
            self.w.files.upload(file_path=path, contents=BytesIO(data), overwrite=True)
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)

    def read_bytes(self, path: str) -> bytes:
        if self.is_volume_path(path):
            return self.w.files.download(path).contents.read()
        with open(path, "rb") as f:
            return f.read()

    # -- embeddings -----------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([("text", text)])[0]

    def embed_image(self, image: bytes | str) -> list[float]:
        data = image if isinstance(image, bytes) else self.read_bytes(image)
        return self.embed_batch([("image", data)])[0]

    def embed_batch(
        self,
        records: list[tuple[str, str | bytes]],
        batch_size: int = 4,
    ) -> list[list[float]]:
        """Embed a mixed batch of (kind, payload) where kind is 'text' or 'image'."""
        out: list[list[float]] = []
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            payload = []
            for kind, data in chunk:
                if kind == "image":
                    if isinstance(data, str):
                        data = self.read_bytes(data)
                    encoded = base64.b64encode(data).decode("utf-8")
                    payload.append({"input_type": "image", "input_data": encoded})
                elif kind == "text":
                    payload.append({"input_type": "text", "input_data": data})
                else:
                    raise ValueError(f"unknown kind {kind!r}; expected 'text' or 'image'")
            response = self.w.serving_endpoints.query(
                name=self.embedding_endpoint,
                dataframe_records=payload,
            )
            out.extend(pred["embedding"] for pred in response.predictions)
        return out

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None


# ---------------------------------------------------------------------------
# ImageGen
# ---------------------------------------------------------------------------


class ImageGen:
    """Async image generation + editing + prompt rewriting.

    Every successful generate / edit call writes the image to UC Volume, runs analysis,
    computes a SigLIP embedding, and inserts a row into Lakebase — there is no separate
    `commit` step. Persistence runs concurrently per image via `asyncio.gather`.

    Two flavors of the public API:
      - `generate` / `edit` — async; return `list[GeneratedImage]` once everything is persisted.
      - `stream_generate` / `stream_edit` — async generators yielding `GenerateEvent`s, suitable
        for SSE-style progressive UX (partial frames → image_done → saved per image).
    """

    def __init__(
        self,
        workspace: VisionWorkspace,
        output_root: str,
        reasoning_model: str = "databricks-gpt-5-5",
        image_model: str = "gpt-image-2",
        thumb_max_width: int = 768,
        refresh_interval: float = 5.0,
        analyzer: "ImageAnalyzer | None" = None,
        openai_client: AsyncOpenAI | None = None,
    ):
        """
        Args:
            workspace: VisionWorkspace providing auth, Lakebase pool, and SigLIP embeddings.
            output_root: UC Volume path where images are persisted (e.g. "/Volumes/cat/sch/vol").
            analyzer: optional pre-built ImageAnalyzer; if None, one is created on first persist
                using the same workspace.
            openai_client: optional OpenAI client override. When supplied (typically a per-request
                OBO-authenticated client minted via `VisionWorkspace.openai_for_token`), generate/
                edit/rewrite use it while Lakebase + SigLIP keep using the workspace's SP-bound
                client.
        """
        if image_model not in MODEL_PRESETS:
            raise ValueError(
                f"unknown image_model {image_model!r}; known: {sorted(MODEL_PRESETS)}"
            )
        if not isinstance(workspace, VisionWorkspace):
            raise TypeError(
                f"expected VisionWorkspace, got {type(workspace).__name__}"
            )
        if not VisionWorkspace.is_volume_path(output_root):
            raise ValueError(
                f"output_root must be a UC Volume path (starting with '/Volumes/'); got {output_root!r}"
            )
        self.workspace = workspace
        self._openai_override = openai_client
        self._analyzer = analyzer
        self.output_root = output_root.rstrip("/")
        self.reasoning_model = reasoning_model
        self.image_model = image_model
        self.thumb_max_width = thumb_max_width
        self.refresh_interval = refresh_interval

    @property
    def client(self) -> AsyncOpenAI:
        return self._openai_override or self.workspace.openai

    @property
    def analyzer(self) -> "ImageAnalyzer":
        if self._analyzer is None:
            self._analyzer = ImageAnalyzer(self.workspace)
        return self._analyzer

    # -- public API -----------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        n: int = 4,
        file_prefix: str = "image",
        criteria: str | None = None,
        batch_id: str | None = None,
        batch_name: str = "",
        folder: str = "default",
        display_progress: bool = True,
        **tool_overrides,
    ) -> list[GeneratedImage]:
        """Generate *n* images in parallel from *prompt*; persist each to UC Volume + Lakebase.

        Each returned `GeneratedImage` is already saved (Volume), analyzed, embedded (SigLIP),
        and inserted into `generated_images`, under a `batch_runs` row (auto-created if no
        `batch_id` is supplied). For SSE-style progressive UX, use `stream_generate`.

        Args:
            criteria: optional user-supplied evaluation criteria forwarded to the analyzer.
            batch_id: existing 8-char batch id (e.g. one the FastAPI app pre-created). If None,
                a new batch_runs row is created.
            batch_name: optional human-friendly name for the auto-created batch.
            folder: folder name for the batch (defaults to "default").
        """
        return await self._consume_stream(
            self.stream_generate(
                prompt,
                n=n,
                file_prefix=file_prefix,
                criteria=criteria,
                batch_id=batch_id,
                batch_name=batch_name,
                folder=folder,
                **tool_overrides,
            ),
            n=n,
            display_progress=display_progress,
        )

    async def stream_generate(
        self,
        prompt: str,
        n: int = 4,
        file_prefix: str = "image",
        criteria: str | None = None,
        batch_id: str | None = None,
        batch_name: str = "",
        folder: str = "default",
        persist: bool = True,
        **tool_overrides,
    ) -> AsyncIterator[GenerateEvent]:
        """Async-iterate `GenerateEvent`s as *n* images stream and persist in parallel.

        Yields `partial` (frame bytes), `image_done` (final bytes per image), `saved` (image
        persisted with id/batch_id/storage_path/analysis), and `error` events.

        Args:
            persist: when False, skip Volume + analyze + embed + DB insert and emit only
                `partial` / `image_done` / `error`. The caller is responsible for any
                persistence. Used by the FastAPI app, which has its own filename/folder/
                thumbnail conventions.
        """
        tools, image_model = self._build_tools(**tool_overrides)
        async for ev in self._stream_run(
            api_input=prompt,
            tools=tools,
            image_model=image_model,
            prompt=prompt,
            n=n,
            file_prefix=file_prefix,
            criteria=criteria,
            batch_id=batch_id,
            batch_name=batch_name,
            folder=folder,
            persist=persist,
            parallel=True,
        ):
            yield ev

    async def edit(
        self,
        prompt: str,
        images: list[str | bytes] | str | bytes,
        n: int = 1,
        file_prefix: str = "edit",
        criteria: str | None = None,
        batch_id: str | None = None,
        batch_name: str = "",
        folder: str = "default",
        display_progress: bool = True,
        **tool_overrides,
    ) -> list[GeneratedImage]:
        """Edit existing images. *images* is a path, raw bytes, or a list of either (up to 4)."""
        return await self._consume_stream(
            self.stream_edit(
                prompt,
                images,
                n=n,
                file_prefix=file_prefix,
                criteria=criteria,
                batch_id=batch_id,
                batch_name=batch_name,
                folder=folder,
                **tool_overrides,
            ),
            n=n,
            display_progress=display_progress,
        )

    async def stream_edit(
        self,
        prompt: str,
        images: list[str | bytes] | str | bytes,
        n: int = 1,
        file_prefix: str = "edit",
        criteria: str | None = None,
        batch_id: str | None = None,
        batch_name: str = "",
        folder: str = "default",
        persist: bool = True,
        **tool_overrides,
    ) -> AsyncIterator[GenerateEvent]:
        """Streaming form of `edit`. *images* may be paths or raw bytes (or a mix).

        See `stream_generate` for the `persist` flag semantics.
        """
        tools, image_model = self._build_tools(**tool_overrides)

        if isinstance(images, (str, bytes)):
            images = [images]

        content: list[dict] = [{"type": "input_text", "text": prompt}]
        for src in images[:4]:
            b64 = self._compress_for_upload(src)
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"})

        api_input = [{"role": "user", "content": content}]

        async for ev in self._stream_run(
            api_input=api_input,
            tools=tools,
            image_model=image_model,
            prompt=prompt,
            n=n,
            file_prefix=file_prefix,
            criteria=criteria,
            batch_id=batch_id,
            batch_name=batch_name,
            folder=folder,
            persist=persist,
            parallel=n == 1,
        ):
            yield ev

    async def rewrite(
        self,
        prompt: str | None = None,
        images: list[str] | str | None = None,
        instructions: str | None = None,
    ) -> str:
        """Rewrite a prompt using the reasoning model. Three modes:

        1. **prompt only** — optimize a text-to-image scene description for gpt-image-2.
        2. **prompt + images** — refine an edit prompt using source images as context.
        3. **images + instructions** — generate a prompt from an image + user direction
           (e.g., "produce a prompt that recreates this image precisely").
        """
        if not prompt and not images:
            raise ValueError("rewrite() requires at least one of `prompt` or `images`.")

        if isinstance(images, str):
            images = [images]
        images = images or []

        if images and not instructions and not prompt:
            raise ValueError(
                "rewrite() with `images` but no `instructions` is edit-prompt mode and "
                "needs a `prompt` to refine. Pass `instructions=...` for image-driven "
                "prompt synthesis instead."
            )

        if images and instructions:
            mode_prompt = instructions
            sys_prompt = (
                "You analyze input image(s) and follow the user's instructions to produce a "
                "single, polished text-to-image prompt. Return ONLY the prompt — no commentary, "
                "no quotes, no markdown."
            )
        elif images:
            mode_prompt = (
                f"Refine this edit instruction so it is precise, faithful to the source image(s), "
                f'and unambiguous for an image-editing model:\n\n"{prompt}"\n\n'
                "Return ONLY the refined instruction."
            )
            sys_prompt = (
                "You optimize edit instructions for image-editing models. Use the source image(s) "
                "as visual context. Be concrete about what to change, what to preserve, and how."
            )
        else:
            mode_prompt = (
                f'Rewrite this prompt as a vivid, detailed scene description optimized for '
                f'gpt-image-2: "{prompt}". Add specifics for composition, lighting, style, and '
                f"mood that would naturally suit the subject. Return ONLY the rewritten prompt."
            )
            sys_prompt = (
                "You optimize text-to-image prompts for gpt-image-2. Produce a single concise "
                "but evocative prompt. No preamble, no quotes."
            )

        content: list[dict] = [{"type": "input_text", "text": mode_prompt}]
        for path in images[:4]:
            b64 = self._compress_for_upload(path)
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"})

        response = await self.client.responses.create(
            model=self.reasoning_model,
            input=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": content},
            ],
        )
        return response.output_text.strip().strip('"').strip("'")

    async def _persist(
        self,
        img: GeneratedImage,
        *,
        batch_id: str,
        image_id: int,
        file_prefix: str,
        criteria: str | None,
    ) -> None:
        """Write to Volume → analyze → embed → insert into generated_images. Mutates *img*
        in-place with batch_id/id/storage_path/analysis.

        The Volume write happens before analyze/embed/insert; if a later step fails the file
        remains as an orphan (no DB row). `ImageAdmin.ingest` reconciles, `ImageAdmin.delete_all`
        wipes.
        """
        suffix = uuid4().hex[:8]
        filename = f"{file_prefix}_{suffix}.png"
        img.storage_path = f"{self.output_root}/{filename}"
        await asyncio.to_thread(self.workspace.write_bytes, img.storage_path, img.bytes)

        img.analysis = await self.analyzer.analyze(img.bytes, gen_prompt=img.prompt, criteria=criteria)

        embedding = await asyncio.to_thread(self.workspace.embed_image, img.bytes)

        a = img.analysis
        description = a.description if a else None
        tags_json = json.dumps(a.tags) if a and a.tags else "[]"
        evaluation = a.evaluation if a else None
        metrics_json = json.dumps(a.metrics.model_dump()) if a else None
        missing_json = json.dumps(a.missing_or_wrong_elements) if a else "[]"
        safety_json = json.dumps(a.safety_flags) if a else "[]"
        brand_json = json.dumps(a.brand_conflicts) if a else "[]"
        improved = a.improved_prompt if a else None
        criteria_eval = a.criteria_evaluation if a else None

        def _insert() -> None:
            with self.workspace.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO generated_images
                      (id, batch_id, image_name, prompt, status, volume_path,
                       description, tags,
                       evaluation, metrics, missing_elements, safety_flags, brand_conflicts, improved_prompt,
                       image_model, size, criteria_evaluation, embedding)
                    VALUES (%s, %s, %s, %s, 'success', %s,
                            %s, %s::jsonb,
                            %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s,
                            %s, %s, %s, %s)
                    """,
                    (
                        image_id, batch_id, filename, img.prompt, img.storage_path,
                        description, tags_json,
                        evaluation, metrics_json, missing_json, safety_json, brand_json, improved,
                        img.image_model, img.size, criteria_eval, embedding,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_insert)
        img.batch_id = batch_id
        img.id = image_id

    def show(
        self,
        items: list[bytes | str | GeneratedImage | SearchResult],
        titles: list[str] | None = None,
        query: bytes | str | GeneratedImage | None = None,
    ) -> None:
        """Display images in a scrollable row with optional per-item titles.

        Items can be raw bytes, file paths, GeneratedImage, or SearchResult.
        SearchResult inputs auto-render with a `sim=… / filename` title if `titles` is None.

        If `query` is provided, it is rendered as the first cell with a bold "QUERY" caption
        and a divider — useful for previewing image-to-image search results.
        """
        if isinstance(items, (bytes, str)) or hasattr(items, "bytes"):
            items = [items]

        rendered: list[bytes | None] = []
        auto_titles: list[str] = []
        query_indices: set[int] = set()

        if query is not None:
            q_bytes, q_label = self._resolve_image_for_show(query)
            rendered.append(q_bytes)
            auto_titles.append(f"QUERY\n{q_label}" if q_label else "QUERY")
            query_indices.add(0)

        for it in items:
            if isinstance(it, bytes) or it is None:
                rendered.append(it)
                auto_titles.append("")
            elif isinstance(it, str):
                rendered.append(self.workspace.read_bytes(it))
                auto_titles.append(os.path.basename(it))
            elif isinstance(it, GeneratedImage):
                rendered.append(it.bytes)
                auto_titles.append(os.path.basename(it.storage_path) if it.storage_path else "")
            elif isinstance(it, SearchResult):
                rendered.append(it.bytes())
                auto_titles.append(f"sim={it.similarity:.3f}\n{os.path.basename(it.storage_path)}")
            else:
                raise TypeError(f"unsupported item type: {type(it).__name__}")

        # If caller passed `titles`, prepend a placeholder for the QUERY label so indices align.
        effective_titles = titles
        if titles is not None and query is not None:
            effective_titles = [auto_titles[0]] + list(titles)

        from IPython.display import display
        display(self._row_html(rendered, effective_titles or auto_titles, query_indices=query_indices))

    def _resolve_image_for_show(
        self, item: bytes | str | GeneratedImage
    ) -> tuple[bytes, str]:
        """Return (bytes, label) for use as a `show(query=...)` argument."""
        if isinstance(item, bytes):
            return item, ""
        if isinstance(item, str):
            return self.workspace.read_bytes(item), os.path.basename(item)
        if isinstance(item, GeneratedImage):
            label = os.path.basename(item.storage_path) if item.storage_path else ""
            return item.bytes, label
        raise TypeError(f"unsupported query type: {type(item).__name__}")

    # -- internal engine ------------------------------------------------------

    async def _stream_run(
        self,
        *,
        api_input,
        tools,
        image_model: str,
        prompt: str,
        n: int,
        file_prefix: str,
        criteria: str | None,
        batch_id: str | None,
        batch_name: str,
        folder: str,
        persist: bool = True,
        parallel: bool = True,
    ) -> AsyncIterator[GenerateEvent]:
        """Drive *n* parallel (or sequential) generation tasks, yielding events as they progress.

        Each task: stream from Responses API → emit partial frames → emit image_done → (if
        `persist`) Volume write + analyze + embed + DB insert → emit saved. On exception emits
        error and continues. Auto-creates a `batch_runs` row when persisting and no `batch_id`
        is supplied.

        When `persist=False`, no DB or Volume writes happen and no `saved` event is emitted —
        the caller is expected to handle persistence (used by the FastAPI app, which has its
        own filename / folder / thumbnail conventions).
        """
        size = tools.get("size")
        queue: asyncio.Queue[GenerateEvent | None] = asyncio.Queue()

        if persist:
            if batch_id is None:
                batch_id = uuid4().hex[:8]
            await asyncio.to_thread(
                self._ensure_batch_run, batch_id, prompt, batch_name, folder, n,
            )

        successful = 0

        async def stream_and_persist(idx: int) -> None:
            nonlocal successful
            try:
                response = await self.client.responses.create(
                    model=self.reasoning_model,
                    input=api_input,
                    tools=[tools],
                    stream=True,
                )
                final_b64: str | None = None
                async for chunk in response:
                    if chunk.type == "response.image_generation_call.partial_image":
                        queue.put_nowait(GenerateEvent(
                            type="partial", index=idx, bytes_b64=chunk.partial_image_b64,
                        ))
                    elif (
                        chunk.type == "response.output_item.done"
                        and chunk.item.type == "image_generation_call"
                    ):
                        final_b64 = chunk.item.result
                        queue.put_nowait(GenerateEvent(
                            type="image_done", index=idx, bytes_b64=final_b64,
                        ))
                if final_b64 is None:
                    queue.put_nowait(GenerateEvent(
                        type="error", index=idx, error="no image bytes received",
                    ))
                    return
                if persist:
                    img = GeneratedImage(
                        bytes=base64.b64decode(final_b64),
                        prompt=prompt,
                        image_model=image_model,
                        size=size,
                    )
                    await self._persist(
                        img,
                        batch_id=batch_id,
                        image_id=idx + 1,
                        file_prefix=file_prefix,
                        criteria=criteria,
                    )
                    successful += 1
                    queue.put_nowait(GenerateEvent(type="saved", index=idx, image=img))
            except BaseException as exc:
                queue.put_nowait(GenerateEvent(type="error", index=idx, error=repr(exc)))

        async def producer() -> None:
            if parallel:
                await asyncio.gather(*[stream_and_persist(i) for i in range(n)])
            else:
                for i in range(n):
                    await stream_and_persist(i)
            if persist:
                await asyncio.to_thread(self._finalize_batch_run, batch_id, successful)
            queue.put_nowait(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield ev
        finally:
            await producer_task

    def _ensure_batch_run(
        self,
        batch_id: str,
        prompt: str,
        batch_name: str,
        folder: str,
        total: int,
    ) -> None:
        with self.workspace.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO batch_runs
                  (batch_id, batch_name, batch_mode, prompt_template,
                   status, total_images, output_volume_path, folder)
                VALUES (%s, %s, 'single', %s, 'running', %s, %s, %s)
                ON CONFLICT (batch_id) DO NOTHING
                """,
                (batch_id, batch_name, prompt, total, self.output_root, folder),
            )
            conn.commit()

    def _finalize_batch_run(self, batch_id: str, successful: int) -> None:
        with self.workspace.pool.connection() as conn:
            conn.execute(
                """
                UPDATE batch_runs
                   SET successful_images = %s,
                       status = CASE
                                  WHEN successful_images >= total_images THEN 'completed'
                                  WHEN %s = 0 THEN 'failed'
                                  ELSE 'completed'
                                END
                 WHERE batch_id = %s
                """,
                (successful, successful, batch_id),
            )
            conn.commit()

    async def _consume_stream(
        self,
        stream: AsyncIterator[GenerateEvent],
        *,
        n: int,
        display_progress: bool,
    ) -> list[GeneratedImage]:
        """Drain *stream* into a list[GeneratedImage], with optional Jupyter progress refresh."""
        if display_progress:
            from IPython.display import clear_output, display
        images: list[GeneratedImage | None] = [None] * n
        bytes_buf: list[bytes | None] = [None] * n
        last_refresh = 0.0
        errors: list[str] = []

        async for ev in stream:
            if ev.type in ("partial", "image_done"):
                bytes_buf[ev.index] = base64.b64decode(ev.bytes_b64)
                now = asyncio.get_event_loop().time()
                if display_progress and (now - last_refresh) > self.refresh_interval:
                    clear_output(wait=True)
                    finished = sum(1 for img in images if img is not None)
                    print(f"Streaming {n} image(s)... ({finished}/{n} saved)")
                    display(self._row_html(bytes_buf))
                    last_refresh = now
            elif ev.type == "saved":
                images[ev.index] = ev.image
            elif ev.type == "error":
                errors.append(f"#{ev.index}: {ev.error}")

        if display_progress:
            clear_output(wait=True)
            display(self._row_html(bytes_buf))

        if errors and not any(images):
            raise RuntimeError("; ".join(errors))
        if errors:
            sys.stderr.write(f"[ImageGen] partial failure: {'; '.join(errors)}\n")

        return [img for img in images if img is not None]

    # -- helpers --------------------------------------------------------------

    def _build_tools(self, **overrides) -> tuple[dict, str]:
        """Build the image-generation tool dict + the image_model that will be used.

        Auto-routes `background='transparent'` to gpt-image-1.5 (the only model that supports it).
        """
        effective_model = self.image_model
        if (
            overrides.get("background") == "transparent"
            and not MODEL_PRESETS[effective_model]["supports_transparent"]
        ):
            sys.stderr.write(
                f"[ImageGen] background='transparent' is not supported by {effective_model}; "
                "switching to gpt-image-1.5 for this call.\n"
            )
            effective_model = "gpt-image-1.5"

        preset = MODEL_PRESETS[effective_model]
        tools = {"type": "image_generation", "model": effective_model, **preset["defaults"]}
        tools.update(overrides)
        if not preset.get("supports_input_fidelity", False):
            tools.pop("input_fidelity", None)
        return tools, effective_model

    def _thumb(self, img_bytes: bytes) -> bytes:
        img = PILImage.open(BytesIO(img_bytes))
        if img.width > self.thumb_max_width:
            ratio = self.thumb_max_width / img.width
            img = img.resize((self.thumb_max_width, int(img.height * ratio)))
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            bg = self._checkerboard(img.size)
            bg.paste(img, mask=img.split()[3])
            img = bg
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    @staticmethod
    def make_thumbnail_bytes(img_bytes: bytes, max_side: int = 400, quality: int = 82) -> bytes:
        """Generate a WebP thumbnail (square-bounded by max_side) from raw image bytes."""
        img = PILImage.open(BytesIO(img_bytes))
        img.thumbnail((max_side, max_side), PILImage.LANCZOS)
        buf = BytesIO()
        img.convert("RGB").save(buf, format="WEBP", quality=quality)
        return buf.getvalue()

    @staticmethod
    def _checkerboard(size: tuple[int, int], block: int = 10) -> PILImage.Image:
        w, h = size
        tile = PILImage.new("RGB", (block * 2, block * 2), (255, 255, 255))
        grey = PILImage.new("RGB", (block, block), (204, 204, 204))
        tile.paste(grey, (block, 0))
        tile.paste(grey, (0, block))
        checker = PILImage.new("RGB", (w, h))
        for y in range(0, h, block * 2):
            for x in range(0, w, block * 2):
                checker.paste(tile, (x, y))
        return checker

    def _row_html(
        self,
        images: list[bytes | None],
        titles: list[str] | None = None,
        query_indices: set[int] | None = None,
    ) -> HTML:
        query_indices = query_indices or set()
        cells = []
        for i, img in enumerate(images):
            is_query = i in query_indices
            title = (titles[i] if titles and i < len(titles) else "") or ""
            if title:
                cap_style = (
                    "font-family:sans-serif;font-size:13px;font-weight:700;color:#1a73e8;"
                    "text-align:center;margin-top:6px;white-space:pre-line"
                    if is_query
                    else "font-family:sans-serif;font-size:11px;color:#444;"
                    "text-align:center;margin-top:4px;white-space:pre-line"
                )
                caption = f'<div style="{cap_style}">{title}</div>'
            else:
                caption = ""

            if img:
                b64 = base64.b64encode(self._thumb(img)).decode()
                img_style = (
                    "height:450px;width:auto;display:block;border-radius:4px"
                    + (";box-shadow:0 0 0 3px #1a73e8" if is_query else "")
                )
                cell = f'<img src="data:image/jpeg;base64,{b64}" style="{img_style}">'
            else:
                cell = (
                    '<div style="height:450px;aspect-ratio:3/2;background:#f0f0f0;border-radius:4px;'
                    'display:flex;align-items:center;justify-content:center;'
                    f'color:#999;font-family:sans-serif">Image {i + 1}</div>'
                )

            wrapper_style = (
                "flex:0 0 auto"
                + (";margin-right:16px;padding-right:16px;border-right:2px dashed #d2e3fc"
                   if is_query else "")
            )
            cells.append(f'<div style="{wrapper_style}">{cell}{caption}</div>')

        from IPython.display import HTML
        return HTML(
            '<div style="display:flex;gap:8px;overflow-x:auto;padding:4px 0;align-items:flex-start">'
            + "".join(cells)
            + "</div>"
        )

    @staticmethod
    def _compress_for_upload(src: str | bytes, max_side: int = 2048, quality: int = 95) -> str:
        """Compress a path-or-bytes image to a base64 JPEG (max_side bound) for inline upload."""
        img = PILImage.open(BytesIO(src) if isinstance(src, bytes) else src)
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# ImageAnalyzer
# ---------------------------------------------------------------------------


class ImageAnalyzer:
    """Produce a structured description + tags for an image using a reasoning model.

    Optional user-supplied `criteria` (e.g., brand or style guidelines) is appended to the
    prompt and the model fills `criteria_evaluation` with a concise assessment against it.
    """

    def __init__(
        self,
        workspace: VisionWorkspace,
        model: str = "databricks-gpt-5-5",
        openai_client: AsyncOpenAI | None = None,
    ):
        """
        Args:
            workspace: VisionWorkspace providing the OpenAI client + Volume read access.
            openai_client: optional override (e.g. a per-request OBO client from
                `VisionWorkspace.openai_for_token`). Falls back to the workspace's own client.
        """
        if not isinstance(workspace, VisionWorkspace):
            raise TypeError(f"expected VisionWorkspace, got {type(workspace).__name__}")
        self._workspace = workspace
        self._openai_override = openai_client
        self.model = model

    @property
    def client(self) -> AsyncOpenAI:
        return self._openai_override or self._workspace.openai

    async def analyze(
        self,
        image: bytes | str,
        gen_prompt: str | None = None,
        criteria: str | None = None,
    ) -> ImageAnalysis:
        """Analyze *image* and return a structured `ImageAnalysis`.

        Args:
            gen_prompt: optional original generation prompt — when supplied, included as
                context so the analyzer can compare the image against the asked-for content.
            criteria: optional user-supplied evaluation criteria (brand, style guidelines, etc.).
                When provided, the model returns a `criteria_evaluation` paragraph.
        """
        if isinstance(image, bytes):
            data = image
            mime = "image/png"
        else:
            data = self._workspace.read_bytes(image)
            ext = image.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
            mime = f"image/{ext}"

        b64 = base64.b64encode(data).decode()

        user_parts: list[str] = []
        if gen_prompt:
            user_parts.append(f"Original generation prompt:\n{gen_prompt}")
        if criteria:
            user_parts.append(f"Evaluation criteria:\n{criteria}")
        user_parts.append("Provide a structured analysis.")
        user_text = "\n\n".join(user_parts)

        r = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "input_text", "text": user_text},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                ]},
            ],
            text_format=ImageAnalysis,
        )
        return r.output_parsed

    async def generate_filename(self, prompt: str) -> str:
        """Generate a short, filesystem-safe filename stem (no extension) from *prompt*.

        The model is asked for 2-4 lowercase words separated by underscores; the result is
        sanitised down to `[a-z0-9_]` and capped at 60 chars. Falls back to "image" if the
        model returns nothing usable.
        """
        import re

        response = await self.client.responses.create(
            model=self.model,
            input=(
                "Generate a short, concise filename (2-4 words, lowercase, "
                "separated by underscores, no extension) for an image created "
                f'from this prompt: "{prompt}". '
                "Return ONLY the filename, nothing else."
            ),
        )
        raw = response.output_text.strip().strip('"').strip("'")
        clean = re.sub(r"[^a-z0-9_]", "_", raw.lower())
        clean = re.sub(r"_+", "_", clean).strip("_")
        return clean[:60] or "image"


# ---------------------------------------------------------------------------
# ImageSearch
# ---------------------------------------------------------------------------


class ImageSearch:
    """pgvector-backed similarity search over committed images."""

    def __init__(self, workspace: VisionWorkspace):
        self.workspace = workspace

    def text(self, query: str, k: int = 5) -> list[SearchResult]:
        return self._search(self.workspace.embed_text(query), k=k, exclude_path=None)

    def image(
        self,
        image: bytes | str,
        k: int = 5,
        exclude_self: bool = True,
    ) -> list[SearchResult]:
        emb = self.workspace.embed_image(image)
        exclude_path = image if (exclude_self and isinstance(image, str)) else None
        return self._search(emb, k=k, exclude_path=exclude_path)

    def recent(self, n: int = 20) -> list[SearchResult]:
        with self.workspace.pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT batch_id, id, volume_path AS storage_path, prompt, description
                FROM generated_images
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (n,),
            ).fetchall()
        return [
            SearchResult(
                batch_id=row["batch_id"],
                id=row["id"],
                storage_path=row["storage_path"],
                prompt=row["prompt"],
                description=row["description"],
                similarity=0.0,
                _workspace=self.workspace,
            )
            for row in rows
        ]

    def _search(
        self,
        embedding: list[float],
        k: int,
        exclude_path: str | None,
    ) -> list[SearchResult]:
        sql = """
            SELECT batch_id, id, volume_path AS storage_path, prompt, description,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM generated_images
            WHERE embedding IS NOT NULL
        """
        params: list[Any] = [embedding]
        if exclude_path:
            sql += " AND volume_path <> %s"
            params.append(exclude_path)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([embedding, k])

        with self.workspace.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            SearchResult(
                batch_id=row["batch_id"],
                id=row["id"],
                storage_path=row["storage_path"],
                prompt=row["prompt"],
                description=row["description"],
                similarity=float(row["similarity"]),
                _workspace=self.workspace,
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# ImageAdmin — maintenance / housekeeping operations
# ---------------------------------------------------------------------------


_DESCRIBE_PROMPT = (
    "Describe this image in 1-2 concise sentences. "
    "Be specific about subjects, setting, colors, and style. No preamble, no quotes."
)


class ImageAdmin:
    """Maintenance operations: wipe assets, ingest manually-uploaded images.

    Both methods are scoped to a UC Volume `output_root` — they refuse to operate on
    local paths to keep destructive actions narrow and auditable.

    ```python
    admin = ImageAdmin(vw, output_root="/Volumes/akopp/image_gen/blogpost")
    admin.delete_all(confirm=False)         # dry-run: returns counts
    admin.delete_all(confirm=True)          # actually wipes table + Volume files
    await admin.ingest()                    # describe + embed + insert every new image
    ```
    """

    def __init__(
        self,
        workspace: VisionWorkspace,
        output_root: str,
        reasoning_model: str = "databricks-gpt-5-5",
    ):
        self.workspace = workspace
        self.output_root = output_root.rstrip("/")
        self.reasoning_model = reasoning_model

    # -- delete --------------------------------------------------------------

    def delete_all(self, confirm: bool = False) -> dict:
        """Wipe every row in `generated_images` (cascading to image_versions) and every file
        under `output_root` in the Volume. Also drops the parent `batch_runs` rows.

        Refuses to run on a local `output_root` — Volume-only by design. Pass
        `confirm=True` to actually delete; otherwise this is a dry run that returns
        what *would* be deleted.
        """
        if not VisionWorkspace.is_volume_path(self.output_root):
            raise RuntimeError(
                f"delete_all() refuses to operate on a non-Volume output_root "
                f"({self.output_root!r}); this method is Volume-only."
            )

        with self.workspace.pool.connection() as conn:
            n_rows = conn.execute(
                "SELECT COUNT(*) AS n FROM generated_images WHERE volume_path LIKE %s",
                (f"{self.output_root}/%",),
            ).fetchone()["n"]

        files = self._list_volume_files(self.output_root)

        if not confirm:
            return {
                "would_delete_rows": n_rows,
                "would_delete_files": len(files),
                "confirmed": False,
            }

        # Rows first: if file deletion fails midway we have orphan files (recoverable)
        # rather than rows pointing at missing files (broken queries). Cascade through
        # image_versions and remove now-empty batch_runs.
        with self.workspace.pool.connection() as conn:
            conn.execute(
                "DELETE FROM generated_images WHERE volume_path LIKE %s",
                (f"{self.output_root}/%",),
            )
            conn.execute(
                """
                DELETE FROM batch_runs
                WHERE NOT EXISTS (
                    SELECT 1 FROM generated_images gi WHERE gi.batch_id = batch_runs.batch_id
                )
                """
            )
            conn.commit()

        deleted = 0
        for path in files:
            try:
                self.workspace.w.files.delete(file_path=path)
                deleted += 1
            except Exception as exc:
                sys.stderr.write(f"[ImageAdmin] failed to delete {path}: {exc}\n")

        return {"rows_deleted": n_rows, "files_deleted": deleted, "confirmed": True}

    # -- ingest --------------------------------------------------------------

    async def ingest(
        self,
        path: str | None = None,
        extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp"),
        skip_existing: bool = True,
        concurrency: int = 4,
    ) -> list[dict]:
        """Scan a Volume directory; describe + embed + insert each new image.

        For each unseen image, generates a 1-2 sentence description, computes a SigLIP
        embedding, and appends a row to `generated_images` under a single auto-created
        `batch_runs` row of mode='ingest'. Returns `{batch_id, id, storage_path,
        description}` dicts for inserted rows. Skips files whose `volume_path` is already
        in the database when `skip_existing=True` (the default).
        """
        scan_path = (path or self.output_root).rstrip("/")
        if not VisionWorkspace.is_volume_path(scan_path):
            raise RuntimeError(
                f"ingest() expects a UC Volume path, got {scan_path!r}"
            )

        all_files = self._list_volume_files(scan_path)
        files = [p for p in all_files if p.lower().endswith(extensions)]

        if skip_existing and files:
            with self.workspace.pool.connection() as conn:
                rows = conn.execute(
                    "SELECT volume_path FROM generated_images WHERE volume_path = ANY(%s)",
                    (files,),
                ).fetchall()
            existing = {r["volume_path"] for r in rows}
            files = [f for f in files if f not in existing]

        if not files:
            return []

        # One batch_runs row covers the whole ingest operation.
        batch_id = uuid4().hex[:8]
        with self.workspace.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO batch_runs
                  (batch_id, batch_name, batch_mode, prompt_template,
                   status, total_images, output_volume_path)
                VALUES (%s, 'ingest', 'ingest', '', 'running', %s, %s)
                """,
                (batch_id, len(files), self.output_root),
            )
            conn.commit()

        sem = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(*[
            self._ingest_one(f, idx + 1, batch_id, sem) for idx, f in enumerate(files)
        ])

        with self.workspace.pool.connection() as conn:
            conn.execute(
                "UPDATE batch_runs SET successful_images=%s, status='completed' WHERE batch_id=%s",
                (len(results), batch_id),
            )
            conn.commit()
        return results

    async def _ingest_one(
        self,
        storage_path: str,
        image_id: int,
        batch_id: str,
        sem: asyncio.Semaphore,
    ) -> dict:
        async with sem:
            data = await asyncio.to_thread(self.workspace.read_bytes, storage_path)
            description = await self._describe(data)
            embedding = await asyncio.to_thread(self.workspace.embed_image, data)

            filename = storage_path.rsplit("/", 1)[-1]

            def _insert() -> None:
                with self.workspace.pool.connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO generated_images
                          (id, batch_id, image_name, prompt, status, volume_path,
                           description, image_model, embedding)
                        VALUES (%s, %s, %s, %s, 'success', %s, %s, 'ingested', %s)
                        """,
                        (image_id, batch_id, filename, description, storage_path,
                         description, embedding),
                    )
                    conn.commit()

            await asyncio.to_thread(_insert)

            return {
                "batch_id": batch_id,
                "id": image_id,
                "storage_path": storage_path,
                "description": description,
            }

    async def _describe(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode()
        response = await self.workspace.openai.responses.create(
            model=self.reasoning_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _DESCRIBE_PROMPT},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{b64}",
                        },
                    ],
                }
            ],
        )
        return response.output_text.strip().strip('"').strip("'")

    # -- helpers -------------------------------------------------------------

    def _list_volume_files(self, path: str) -> list[str]:
        """Recursively list every file under a Volume directory."""
        files: list[str] = []
        try:
            entries = list(
                self.workspace.w.files.list_directory_contents(directory_path=path)
            )
        except Exception as exc:
            sys.stderr.write(f"[ImageAdmin] could not list {path}: {exc}\n")
            return files
        for entry in entries:
            if entry.is_directory:
                files.extend(self._list_volume_files(entry.path))
            else:
                files.append(entry.path)
        return files
