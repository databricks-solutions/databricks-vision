"""Single image generation and editing with SSE streaming."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from image_gen import ImageAnalyzer, ImageGen
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sse_starlette.sse import EventSourceResponse

from ..core import Dependencies
from ..core._background import spawn_bg
from ..core._image_gen_dep import _get_user_token, get_image_gen, get_sp_token
from ..core._image_validation import validate_size as _validate_size

router = APIRouter(tags=["generate"])


def _pg_execute(pool: ConnectionPool, sql: str, params: tuple = ()) -> None:
    with pool.connection() as conn:
        conn.execute(sql, params)
        conn.commit()


def _pg_fetch(pool: ConnectionPool, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
    return [dict(r) for r in rows]


def _get_user_ws_from_request(request: Request) -> "WorkspaceClient":
    """SP-bound WorkspaceClient for file / SDK operations done from background tasks.

    Same rationale as core/_defaults._get_user_ws: the OBO token's `files.files`
    scope doesn't satisfy the Files API's `files` requirement, and routing file
    ops via the SP matches the shared-asset use case.
    """
    return request.app.state.workspace_client


def _create_obo_analyzer(request: Request) -> ImageAnalyzer:
    """Build a per-request ImageAnalyzer for the analyzer call.
    Must be called before scheduling the background task — the request goes out of scope
    once the SSE response closes. Currently SP-only; see _get_user_token for the rationale.
    """
    cfg = request.app.state.config
    vw = request.app.state.vision_workspace
    token = _get_user_token(request)
    openai_client = vw.openai_for_token(token) if token else vw.openai
    return ImageAnalyzer(workspace=vw, model=cfg.model_name, openai_client=openai_client)


_FILENAME_FROM_PROMPT_RE = re.compile(r"[^a-z0-9]+")


def _slug_from_prompt(prompt: str, max_words: int = 4) -> str:
    """Cheap, instant filename slug — avoids a second LLM call before DB write."""
    words = _FILENAME_FROM_PROMPT_RE.sub(" ", prompt.lower()).split()
    slug = "_".join(words[:max_words]).strip("_")
    return slug[:40] or "image"


_OUTPUT_FORMAT_TO_EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}


async def _save_and_analyze(
    request: Request,
    user_ws: "WorkspaceClient",
    analyzer: ImageAnalyzer,
    image_bytes: bytes,
    ext: str,
    prompt: str,
    folder: str,
    is_edit: bool,
    criteria: str | None = None,
) -> None:
    """Background task: write the gallery row immediately, then run the analyzer
    asynchronously and UPDATE the row with eval fields when done.

    Writing the row first means a freshly-generated image shows up in the
    gallery within ~2 seconds; the slower structured eval call (5-10s) no
    longer blocks visibility.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        ws = user_ws  # Use OBO-authenticated client for file operations
        cfg = request.app.state.config
        pool: ConnectionPool = request.app.state.db_pool

        # Ensure folder exists in DB
        if pool:
            _pg_execute(pool, "INSERT INTO folders (name) VALUES (%s) ON CONFLICT DO NOTHING", (folder,))

        # Cheap filename slug — skip the LLM round-trip so the image lands fast.
        filename_stem = _slug_from_prompt(prompt)
        filename = f"{filename_stem}{ext}"
        batch_id = str(uuid.uuid4())[:8]

        # Upload image + thumbnail to UC Volume
        volume_path = f"{cfg.vision_volume}/{folder}/{batch_id}/{filename}"
        ws.files.upload(volume_path, BytesIO(image_bytes), overwrite=True)
        thumbnail_bytes = ImageGen.make_thumbnail_bytes(image_bytes)
        thumbnail_path = f"{cfg.vision_volume}/{folder}/{batch_id}/thumb.webp"
        ws.files.upload(thumbnail_path, BytesIO(thumbnail_bytes), overwrite=True)

        # Phase 1 — INSERT row immediately so the image appears in the gallery.
        if pool:
            mode = "edit" if is_edit else "single"
            _pg_execute(
                pool,
                """INSERT INTO batch_runs
                   (batch_id, batch_name, batch_mode, status, created_at,
                    total_images, successful_images, output_volume_path, folder)
                   VALUES (%s, %s, %s, 'completed', NOW(), 1, 1, %s, %s)""",
                (batch_id, prompt[:100], mode, f"{cfg.vision_volume}/{folder}/{batch_id}", folder),
            )
            _pg_execute(
                pool,
                """INSERT INTO generated_images
                   (id, batch_id, image_name, prompt, status, volume_path, thumbnail_path)
                   VALUES (1, %s, %s, %s, 'success', %s, %s)""",
                (batch_id, filename_stem, prompt, volume_path, thumbnail_path),
            )

        # Phase 2 — run the structured analyzer (slow) AND compute the SigLIP
        # embedding in parallel, then UPDATE the row with all eval columns +
        # the embedding. Failures of either step are non-fatal — the image
        # still shows in the gallery, just without that data.
        if not pool:
            return
        vw = request.app.state.vision_workspace
        analyze_task = asyncio.create_task(analyzer.analyze(image_bytes, gen_prompt=prompt, criteria=criteria))
        embed_task = asyncio.create_task(asyncio.to_thread(vw.embed_image, image_bytes))
        analysis = embedding = None
        try:
            analysis = await analyze_task
        except Exception as exc:
            log.warning("Analysis failed for single-gen %s: %s", batch_id, exc)
        try:
            embedding = await embed_task
        except Exception as exc:
            log.warning("Embedding failed for single-gen %s: %s", batch_id, exc)

        if analysis is None and embedding is None:
            return
        if analysis is not None and embedding is not None:
            _pg_execute(
                pool,
                """UPDATE generated_images SET
                      description = %s, tags = %s::jsonb,
                      evaluation = %s, metrics = %s::jsonb,
                      missing_elements = %s::jsonb, safety_flags = %s::jsonb,
                      brand_conflicts = %s::jsonb, improved_prompt = %s,
                      criteria_evaluation = %s, embedding = %s
                   WHERE batch_id = %s AND id = 1""",
                (
                    analysis.description, json.dumps(analysis.tags),
                    analysis.evaluation, json.dumps(analysis.metrics.model_dump()),
                    json.dumps(analysis.missing_or_wrong_elements), json.dumps(analysis.safety_flags),
                    json.dumps(analysis.brand_conflicts), analysis.improved_prompt,
                    analysis.criteria_evaluation, embedding,
                    batch_id,
                ),
            )
        elif analysis is not None:
            _pg_execute(
                pool,
                """UPDATE generated_images SET
                      description = %s, tags = %s::jsonb,
                      evaluation = %s, metrics = %s::jsonb,
                      missing_elements = %s::jsonb, safety_flags = %s::jsonb,
                      brand_conflicts = %s::jsonb, improved_prompt = %s,
                      criteria_evaluation = %s
                   WHERE batch_id = %s AND id = 1""",
                (
                    analysis.description, json.dumps(analysis.tags),
                    analysis.evaluation, json.dumps(analysis.metrics.model_dump()),
                    json.dumps(analysis.missing_or_wrong_elements), json.dumps(analysis.safety_flags),
                    json.dumps(analysis.brand_conflicts), analysis.improved_prompt,
                    analysis.criteria_evaluation,
                    batch_id,
                ),
            )
        else:
            _pg_execute(
                pool,
                "UPDATE generated_images SET embedding = %s WHERE batch_id = %s AND id = 1",
                (embedding, batch_id),
            )
    except Exception as exc:
        log.error("Failed to save generated image: %s", exc, exc_info=True)


@router.post("/generate", operation_id="generateImages")
async def generate_images(
    request: Request,
    prompt: str = Form(...),
    n: int = Form(1),
    folder: str = Form("default"),
    quality: str = Form("auto"),
    size: str = Form("1024x1024"),
    output_format: str = Form("png"),
    background: str = Form("auto"),
    criteria: str = Form(""),
):
    _validate_size(size, transparent=(background == "transparent"))

    image_gen = get_image_gen(request)
    user_ws = _get_user_ws_from_request(request)
    analyzer = _create_obo_analyzer(request)

    tool_overrides = {
        "quality": quality,
        "size": size,
        "output_format": output_format,
        "background": background,
    }
    ext = _OUTPUT_FORMAT_TO_EXT.get(output_format, ".png")
    crit = criteria.strip() or None

    async def event_generator():
        completed = 0
        async for event in image_gen.stream_generate(
            prompt, n=n, persist=False, **tool_overrides,
        ):
            if event.type == "partial":
                yield {
                    "event": "partial",
                    "data": json.dumps({"index": event.index, "image_b64": event.bytes_b64}),
                }
            elif event.type == "image_done":
                yield {
                    "event": "done",
                    "data": json.dumps({"index": event.index, "image_b64": event.bytes_b64}),
                }
                img_bytes = base64.b64decode(event.bytes_b64)
                spawn_bg(_save_and_analyze(
                    request, user_ws, analyzer, img_bytes, ext, prompt, folder, False, crit,
                ))
                completed += 1
            elif event.type == "error":
                yield {
                    "event": "error",
                    "data": json.dumps({"index": event.index, "error": event.error}),
                }

        yield {"event": "complete", "data": json.dumps({"count": completed})}

    return EventSourceResponse(event_generator())


@router.post("/rewrite", operation_id="rewritePrompt")
async def rewrite_prompt(
    request: Request,
    prompt: str = Form(""),
    instructions: str = Form(""),
    images: list[UploadFile] = Form(default=[]),
):
    """Rewrite a generation prompt using ImageGen.rewrite — text-only, image-conditioned,
    or image-driven synthesis depending on which inputs the FE sends.
    """
    image_gen = get_image_gen(request)
    image_bytes_list = []
    for upload in images[:4]:
        image_bytes_list.append(await upload.read())

    if not prompt.strip() and not image_bytes_list:
        raise HTTPException(400, "Provide a prompt and/or at least one image to rewrite from.")

    try:
        rewritten = await image_gen.rewrite(
            prompt=prompt or None,
            images=image_bytes_list or None,
            instructions=instructions or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"rewritten": rewritten}


@router.post("/edit", operation_id="editImages")
async def edit_images(
    request: Request,
    prompt: str = Form(...),
    n: int = Form(1),
    folder: str = Form("default"),
    quality: str = Form("auto"),
    size: str = Form("1024x1024"),
    output_format: str = Form("png"),
    input_fidelity: str = Form("high"),
    background: str = Form("auto"),
    criteria: str = Form(""),
    images: list[UploadFile] = Form(default=[]),
    # `source_*` are accepted for FE compat but no longer used — every edit creates its
    # own gallery row. We keep the params so older form payloads don't 422; we may revive
    # them later for a "view source" link via dedicated columns.
    source_batch_id: str | None = Form(default=None),  # noqa: ARG001
    source_image_id: int | None = Form(default=None),  # noqa: ARG001
):
    image_gen = get_image_gen(request)
    user_ws = _get_user_ws_from_request(request)
    analyzer = _create_obo_analyzer(request)

    image_bytes_list = []
    for upload in images[:4]:
        data = await upload.read()
        image_bytes_list.append(data)

    if not image_bytes_list:
        raise HTTPException(400, "At least one image is required for editing")

    _validate_size(size, transparent=(background == "transparent"))

    tool_overrides = {
        "quality": quality,
        "size": size,
        "output_format": output_format,
        "input_fidelity": input_fidelity,
        "background": background,
    }
    ext = _OUTPUT_FORMAT_TO_EXT.get(output_format, ".png")
    crit = criteria.strip() or None

    async def event_generator():
        completed = 0
        async for event in image_gen.stream_edit(
            prompt, image_bytes_list, n=n, persist=False, **tool_overrides,
        ):
            if event.type == "partial":
                yield {
                    "event": "partial",
                    "data": json.dumps({"index": event.index, "image_b64": event.bytes_b64}),
                }
            elif event.type == "image_done":
                yield {
                    "event": "done",
                    "data": json.dumps({"index": event.index, "image_b64": event.bytes_b64}),
                }
                img_bytes = base64.b64decode(event.bytes_b64)
                # Every edit becomes its own gallery row with its own batch_id, folder,
                # thumbnail, and full analysis — no more updating the source row in place.
                # The "save as new version of source" path was removed because the FE
                # never let users browse those versions for single-image flows, and it
                # produced inconsistent gallery state (stale thumbnail/metadata vs. new image).
                spawn_bg(_save_and_analyze(
                    request, user_ws, analyzer, img_bytes, ext, prompt, folder, True, crit,
                ))
                completed += 1
            elif event.type == "error":
                yield {
                    "event": "error",
                    "data": json.dumps({"index": event.index, "error": event.error}),
                }

        yield {"event": "complete", "data": json.dumps({"count": completed})}

    return EventSourceResponse(event_generator())
