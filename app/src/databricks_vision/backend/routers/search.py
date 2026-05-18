"""Search endpoints — semantic (SigLIP cosine) and FTS, plus by-image / similar-to-row."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..core import Dependencies
from ..models import SearchResponse, SearchResultItem

router = APIRouter(tags=["search"])


def _pg_fetch(pool: ConnectionPool, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
    return [dict(r) for r in rows]


# --- FTS (legacy / opt-in via mode=fts) ---

_DOC_EXPR = """to_tsvector('english',
    coalesce(g.prompt, '') || ' ' ||
    coalesce(g.image_name, '') || ' ' ||
    coalesce(g.variation_label, '') || ' ' ||
    coalesce(g.description, '') || ' ' ||
    coalesce(br.batch_name, '')
)"""

_FTS_SQL = f"""
    SELECT
        g.batch_id,
        g.id AS image_id,
        g.image_name,
        g.prompt,
        g.volume_path,
        g.variation_label,
        g.description,
        g.tags,
        g.thumbnail_path,
        br.batch_name,
        br.batch_mode,
        ts_rank({_DOC_EXPR}, to_tsquery('english', %s)) AS score
    FROM generated_images g
    JOIN batch_runs br ON br.batch_id = g.batch_id
    WHERE
        g.status = 'success'
        AND {_DOC_EXPR} @@ to_tsquery('english', %s)
    ORDER BY score DESC
    LIMIT %s
"""


def _build_prefix_query(user_input: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", user_input)
    if not words:
        return ""
    return " & ".join(f"{w}:*" for w in words)


# --- Semantic (cosine over SigLIP embeddings) ---

# Cosine similarity floor — drop matches that are essentially unrelated. The SigLIP
# distribution typically clusters relevant matches > 0.05 and noise close to 0.
_SIM_FLOOR = 0.05

_SEMANTIC_SQL = """
    SELECT
        g.batch_id,
        g.id AS image_id,
        g.image_name,
        g.prompt,
        g.volume_path,
        g.variation_label,
        g.description,
        g.tags,
        g.thumbnail_path,
        br.batch_name,
        br.batch_mode,
        1 - (g.embedding <=> %s::vector) AS score
    FROM generated_images g
    JOIN batch_runs br ON br.batch_id = g.batch_id
    WHERE g.status = 'success'
      AND g.embedding IS NOT NULL
      {extra_where}
    ORDER BY g.embedding <=> %s::vector
    LIMIT %s
"""


def _semantic_query(
    pool: ConnectionPool,
    embedding: list[float],
    limit: int,
    exclude: tuple[str, int] | None = None,
) -> list[dict[str, Any]]:
    extra_where = ""
    params: list[Any] = [embedding]
    if exclude:
        extra_where = "AND NOT (g.batch_id = %s AND g.id = %s)"
        params.extend([exclude[0], exclude[1]])
    params.extend([embedding, limit])
    rows = _pg_fetch(pool, _SEMANTIC_SQL.format(extra_where=extra_where), tuple(params))
    return [r for r in rows if (r.get("score") or 0) >= _SIM_FLOOR]


def _row_to_item(row: dict) -> SearchResultItem:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    row = {**row, "tags": tags}
    return SearchResultItem(**row)


# --- Routes ---


@router.get("/search", response_model=SearchResponse, operation_id="searchImages")
async def search_images(
    request: Request,
    q: str,
    db: Dependencies.DB,
    mode: str = "semantic",
    limit: int = 40,
):
    """Text → image search. `mode=semantic` (default) runs SigLIP cosine over the
    embedding column; `mode=fts` falls back to Postgres full-text on prompt+description.
    """
    if not q.strip():
        return SearchResponse(results=[], query=q)

    if mode == "fts":
        tsquery = _build_prefix_query(q)
        if not tsquery:
            return SearchResponse(results=[], query=q)
        rows = _pg_fetch(db, _FTS_SQL, (tsquery, tsquery, limit))
        return SearchResponse(results=[_row_to_item(r) for r in rows], query=q)

    # Semantic path: embed the query text, run cosine over generated_images.embedding.
    vw = request.app.state.vision_workspace
    try:
        embedding = await asyncio.to_thread(vw.embed_text, q.strip())
    except Exception as exc:
        raise HTTPException(503, f"Embedding endpoint unavailable: {exc}")
    rows = _semantic_query(db, embedding, limit)
    return SearchResponse(results=[_row_to_item(r) for r in rows], query=q)


@router.post("/search/by-image", response_model=SearchResponse, operation_id="searchByImage")
async def search_by_image(
    request: Request,
    db: Dependencies.DB,
    image: UploadFile,
    limit: int = 40,
):
    """Image → image similarity search. Embed the uploaded image with SigLIP, run cosine."""
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image upload")

    vw = request.app.state.vision_workspace
    try:
        embedding = await asyncio.to_thread(vw.embed_image, data)
    except Exception as exc:
        raise HTTPException(503, f"Embedding endpoint unavailable: {exc}")

    rows = _semantic_query(db, embedding, limit)
    label = image.filename or "uploaded image"
    return SearchResponse(results=[_row_to_item(r) for r in rows], query=label)


@router.get("/search/similar/{batch_id}/{image_id}", response_model=SearchResponse, operation_id="searchSimilar")
async def search_similar(
    request: Request,
    batch_id: str,
    image_id: int,
    db: Dependencies.DB,
    limit: int = 40,
):
    """Find images similar to an existing gallery row using its stored embedding.
    Falls back to embedding the image bytes on demand if the row's embedding is null."""
    rows = _pg_fetch(
        db,
        "SELECT image_name, volume_path, embedding FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    if not rows:
        raise HTTPException(404, "Source image not found")
    src = rows[0]
    embedding = src.get("embedding")

    if embedding is None:
        # Older rows may lack an embedding — compute one on the fly so Find similar still works.
        vol = src.get("volume_path")
        if not vol:
            raise HTTPException(409, "Source row has no volume_path; cannot embed on demand")
        ws = request.app.state.workspace_client
        try:
            data = ws.files.download(vol).contents.read()
            vw = request.app.state.vision_workspace
            embedding = await asyncio.to_thread(vw.embed_image, data)
        except Exception as exc:
            raise HTTPException(503, f"Could not compute embedding for source: {exc}")

    matches = _semantic_query(db, embedding, limit, exclude=(batch_id, image_id))
    label = src.get("image_name") or f"{batch_id}/{image_id}"
    return SearchResponse(results=[_row_to_item(r) for r in matches], query=label)
