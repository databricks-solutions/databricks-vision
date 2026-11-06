"""Single image generation and editing with SSE streaming."""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import re
import uuid
from io import BytesIO
from typing import Any, AsyncIterator, Callable

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from image_gen import (
    FORMAT_PRESETS,
    MAX_INPUT_IMAGES,
    MODEL_PRESETS,
    GenerateEvent,
    ImageAnalyzer,
    ImageGen,
    enabled_image_models,
)
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sse_starlette.sse import EventSourceResponse

from ..core import Dependencies
from ..core._background import spawn_bg
from ..core._eval import metrics_json
from ..core._image_gen_dep import _get_user_token, get_image_gen, get_sp_token
from ..core._image_validation import (
    validate_image_model,
    validate_raster_format,
    validate_tool_request,
)
from ..models import StyleGuidelineOut
from .style_guidelines import get_brand_kit, read_logo
from .volumes import read_volume_image

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
    mode: str,
    tool_meta: dict[str, str],
    criteria: str | None = None,
    title: str | None = None,
) -> None:
    """Background task: write the gallery row immediately, then run the analyzer
    asynchronously and UPDATE the row with eval fields when done.

    Writing the row first means a freshly-generated image shows up in the
    gallery within ~2 seconds; the slower structured eval call (5-10s) no
    longer blocks visibility.

    `mode` ("single" | "edit" | "compose" | "adapt") is recorded as batch_runs.batch_mode.
    `tool_meta` (image_model, size, quality, output_format, background) is recorded on
    the batch_runs row so "regenerate" replays the same settings. `title` names the gallery
    row and file when the prompt is a long generated one (Compose / Adapt).
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
        filename_stem = _slug_from_prompt(title or prompt)
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
            _pg_execute(
                pool,
                """INSERT INTO batch_runs
                   (batch_id, batch_name, batch_mode, status, created_at,
                    total_images, successful_images, output_volume_path, folder,
                    image_model, size, quality, output_format, background)
                   VALUES (%s, %s, %s, 'completed', NOW(), 1, 1, %s, %s, %s, %s, %s, %s, %s)""",
                (batch_id, (title or prompt)[:100], mode, f"{cfg.vision_volume}/{folder}/{batch_id}", folder,
                 tool_meta["image_model"], tool_meta["size"], tool_meta["quality"],
                 tool_meta["output_format"], tool_meta["background"]),
            )
            _pg_execute(
                pool,
                """INSERT INTO generated_images
                   (id, batch_id, image_name, prompt, status, volume_path, thumbnail_path,
                    image_model, size)
                   VALUES (1, %s, %s, %s, 'success', %s, %s, %s, %s)""",
                (batch_id, filename_stem, prompt, volume_path, thumbnail_path,
                 tool_meta["image_model"], tool_meta["size"]),
            )

        # Phase 2 — score the image AND compute the SigLIP embedding in parallel, then
        # UPDATE the row with all eval columns + the embedding. Failures of either step are
        # non-fatal — the image still shows in the gallery, just without that data.
        #
        # Scoring prefers the MLflow ImageEvaluator (traces the image + runs make_judge
        # {{ trace }} judges, mirroring the scores back into the same ImageAnalysis shape).
        # If eval is disabled or the judges fail, we fall back to the plain structured
        # analyzer so the gallery fields are still populated.
        if not pool:
            return
        vw = request.app.state.vision_workspace
        evaluator = getattr(request.app.state, "image_evaluator", None)

        async def _score():
            if evaluator is not None:
                try:
                    return await evaluator.score_image(analyzer, image_bytes, prompt, criteria)
                except Exception as exc:
                    log.warning("MLflow eval failed for single-gen %s; falling back to analyzer: %s", batch_id, exc)
            return await analyzer.analyze(image_bytes, gen_prompt=prompt, criteria=criteria)

        analyze_task = asyncio.create_task(_score())
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
                    analysis.evaluation, metrics_json(analysis),
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
                    analysis.evaluation, metrics_json(analysis),
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


def _sse(event: str, **data: Any) -> dict:
    return {"event": event, "data": json.dumps(data)}


async def _relay_events(
    request: Request,
    events: AsyncIterator[GenerateEvent],
    *,
    ext: str,
    folder: str,
    mode: str,
    prompt_for: Callable[[int], str],
    meta_for: Callable[[int], dict[str, str]],
    criteria: str | None,
    title_for: Callable[[int], str | None] = lambda _: None,
) -> AsyncIterator[dict]:
    """Relay ImageGen events as SSE (partial / done / error, then complete) and persist each
    finished image in the background. Every image becomes its own gallery row with its own
    batch_id, folder, thumbnail and analysis; `prompt_for` / `meta_for` / `title_for` give the
    prompt, tool settings and gallery title recorded for the image at a given event index."""
    user_ws = _get_user_ws_from_request(request)
    analyzer = _create_obo_analyzer(request)
    completed = 0
    async for event in events:
        if event.type == "partial":
            yield _sse("partial", index=event.index, image_b64=event.bytes_b64)
        elif event.type == "image_done":
            yield _sse("done", index=event.index, image_b64=event.bytes_b64)
            spawn_bg(_save_and_analyze(
                request, user_ws, analyzer, base64.b64decode(event.bytes_b64), ext,
                prompt_for(event.index), folder, mode, meta_for(event.index), criteria,
                title_for(event.index),
            ))
            completed += 1
        elif event.type == "error":
            yield _sse("error", index=event.index, error=event.error)
    yield _sse("complete", count=completed)


async def _merge_streams(streams: list[AsyncIterator[GenerateEvent]]) -> AsyncIterator[GenerateEvent]:
    """Run several single-image streams concurrently; stream *i*'s events come out with
    index *i* (Adapt runs one stream per target format, each with its own size)."""
    queue: asyncio.Queue[GenerateEvent | None] = asyncio.Queue()

    async def pump(i: int, stream: AsyncIterator[GenerateEvent]) -> None:
        try:
            async for ev in stream:
                await queue.put(dataclasses.replace(ev, index=i))
        except Exception as exc:
            await queue.put(GenerateEvent(type="error", index=i, error=repr(exc)))
        finally:
            await queue.put(None)

    tasks = [asyncio.create_task(pump(i, s)) for i, s in enumerate(streams)]
    try:
        remaining = len(tasks)
        while remaining:
            ev = await queue.get()
            if ev is None:
                remaining -= 1
            else:
                yield ev
    finally:
        for task in tasks:
            task.cancel()


async def _read_uploads(uploads: list[UploadFile]) -> list[bytes]:
    if len(uploads) > MAX_INPUT_IMAGES:
        raise HTTPException(400, f"At most {MAX_INPUT_IMAGES} images; got {len(uploads)}")
    return [await upload.read() for upload in uploads]


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
    image_model: str = Form(""),
    complexity: str = Form(""),
):
    image_model = image_model or request.app.state.config.image_model
    validate_raster_format(output_format)
    effective_model = validate_tool_request(image_model, background, quality, size, complexity)

    image_gen = get_image_gen(request, image_model)
    tool_overrides = {
        "quality": quality,
        "size": size,
        "output_format": output_format,
        "background": background,
    }
    if complexity:
        tool_overrides["complexity"] = complexity
    tool_meta = {
        "image_model": effective_model, "size": size, "quality": quality,
        "output_format": output_format, "background": background,
    }
    events = image_gen.stream_generate(prompt, n=n, persist=False, **tool_overrides)
    return EventSourceResponse(_relay_events(
        request, events, ext=_OUTPUT_FORMAT_TO_EXT.get(output_format, ".png"), folder=folder,
        mode="single", prompt_for=lambda _: prompt, meta_for=lambda _: tool_meta,
        criteria=criteria.strip() or None,
    ))


@router.post("/rewrite", operation_id="rewritePrompt")
async def rewrite_prompt(
    request: Request,
    prompt: str = Form(""),
    instructions: str = Form(""),
    images: list[UploadFile] = Form(default=[]),
    image_model: str = Form(""),
):
    """Rewrite a generation prompt using ImageGen.rewrite — text-only, image-conditioned,
    or image-driven synthesis depending on which inputs the FE sends.
    """
    image_model = image_model or request.app.state.config.image_model
    image_gen = get_image_gen(request, validate_image_model(image_model))
    image_bytes_list = await _read_uploads(images)

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
    image_model: str = Form(""),
    complexity: str = Form(""),
):
    image_model = image_model or request.app.state.config.image_model
    validate_raster_format(output_format)
    effective_model = validate_tool_request(image_model, background, quality, size, complexity)

    image_gen = get_image_gen(request, image_model)
    image_bytes_list = await _read_uploads(images)
    if not image_bytes_list:
        raise HTTPException(400, "At least one image is required for editing")

    tool_overrides = {
        "quality": quality,
        "size": size,
        "output_format": output_format,
        "input_fidelity": input_fidelity,
        "background": background,
    }
    if complexity:
        tool_overrides["complexity"] = complexity
    tool_meta = {
        "image_model": effective_model, "size": size, "quality": quality,
        "output_format": output_format, "background": background,
    }
    # Every edit becomes its own gallery row — the "save as new version of source" path was
    # removed because the FE never let users browse those versions for single-image flows,
    # and it produced inconsistent gallery state (stale thumbnail/metadata vs. new image).
    events = image_gen.stream_edit(prompt, image_bytes_list, n=n, persist=False, **tool_overrides)
    return EventSourceResponse(_relay_events(
        request, events, ext=_OUTPUT_FORMAT_TO_EXT.get(output_format, ".png"), folder=folder,
        mode="edit", prompt_for=lambda _: prompt, meta_for=lambda _: tool_meta,
        criteria=criteria.strip() or None,
    ))


# --- Compose: role-tagged references + exact copy → one marketing creative ---------------

_COMPOSE_ROLES = {
    "background": "BACKGROUND — use this as the scene and backdrop; keep its setting and camera angle.",
    "product": "PRODUCT — reproduce this product exactly: shape, colours, materials and label "
               "text. Do not redesign it.",
    "logo": "LOGO — place this logo unaltered and fully legible. Do not redraw, recolour or "
            "distort it.",
    "style": "STYLE REFERENCE — match its lighting, colour grading and mood only. Do not copy "
             "its objects or text.",
}
_MAX_PRODUCTS = 3
# Judged alongside the brand kit's own rules (criteria_adherence / brand_conflict judges).
_COMPOSE_CHECKS = (
    "All quoted copy is rendered exactly as written (same words, spelling and capitalisation) "
    "with no extra text; the logo appears unaltered and legible; products match their references."
)


def _format_preset(key: str) -> dict:
    if key not in FORMAT_PRESETS:
        raise HTTPException(400, f"Unknown format {key!r}; expected one of {', '.join(FORMAT_PRESETS)}")
    return FORMAT_PRESETS[key]


def _compose_prompt(
    fmt: dict, *, headline: str, subheadline: str, cta: str, art_direction: str,
    kit: StyleGuidelineOut | None,
) -> str:
    """The Compose instruction; each image's role travels as a label next to that image."""
    w, h = fmt["size"].split("x")
    lines = [
        f"Create a finished {fmt['label'].lower()} marketing creative ({w}×{h}, {fmt['ratio']}) "
        "from the labelled reference images."
    ]
    copy = [
        (label, text.strip())
        for label, text in (
            ("Headline", headline),
            ("Subheadline", subheadline),
            ("Call to action (styled as a button)", cta),
        )
        if text.strip()
    ]
    if copy:
        lines.append(
            "Render this text exactly as written — same words, spelling and capitalisation — "
            "and no other text:"
        )
        lines += [f'- {label}: "{text}"' for label, text in copy]
    else:
        lines.append("Do not add any text beyond what already appears on the product or logo.")
    if kit and kit.palette:
        lines.append(
            f"Brand colours: {', '.join(kit.palette)} — use them for text, accents and the "
            "call to action."
        )
    if kit and kit.typography.strip():
        lines.append(f"Typography: {kit.typography.strip()}")
    if art_direction.strip():
        lines.append(f"Art direction: {art_direction.strip()}")
    lines.append(
        "Layout: one clear focal point and a strong hierarchy (headline, then subheadline, then "
        "call to action) with generous safe margins. Never crop or overlap text, logo or product."
    )
    return "\n".join(lines)


def _parse_brand_kit_id(raw: str) -> int | None:
    if not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(400, f"brand_kit_id must be an integer; got {raw!r}")


@router.post("/compose", operation_id="composeImages")
async def compose_images(
    request: Request,
    format: str = Form("square"),
    headline: str = Form(""),
    subheadline: str = Form(""),
    cta: str = Form(""),
    art_direction: str = Form(""),
    brand_kit_id: str = Form(""),
    background: UploadFile | None = Form(None),
    background_path: str = Form(""),
    products: list[UploadFile] = Form(default=[]),
    product_paths: list[str] = Form(default=[]),
    logo: UploadFile | None = Form(None),
    style_ref: UploadFile | None = Form(None),
    style_ref_path: str = Form(""),
    n: int = Form(1),
    folder: str = Form("default"),
    quality: str = Form("auto"),
    output_format: str = Form("png"),
    image_model: str = Form(""),
    complexity: str = Form(""),
):
    """Compose a marketing creative (poster / social post / banner) from role-tagged reference
    images — background, up to 3 products, logo, style reference — plus exact copy. A brand kit
    supplies the logo (unless one is uploaded), palette and typography, and its rules become the
    judges' criteria. Each slot is an upload or a /Volumes path picked in the volume browser."""
    fmt = _format_preset(format)
    image_model = image_model or request.app.state.config.image_model
    if not complexity and MODEL_PRESETS.get(image_model, {}).get("supports_complexity"):
        complexity = "high"  # many elements + exact text: let the model plan the layout
    validate_raster_format(output_format)
    effective_model = validate_tool_request(image_model, "auto", quality, fmt["size"], complexity)

    kit_id = _parse_brand_kit_id(brand_kit_id)
    kit = get_brand_kit(request.app.state.db_pool, kit_id) if kit_id is not None else None
    ws = _get_user_ws_from_request(request)

    slots: list[tuple[str, bytes]] = []
    if background is not None:
        slots.append(("background", await background.read()))
    elif background_path:
        slots.append(("background", read_volume_image(ws, background_path)))
    if len(products) + len(product_paths) > _MAX_PRODUCTS:
        raise HTTPException(400, f"At most {_MAX_PRODUCTS} product images")
    for upload in products:
        slots.append(("product", await upload.read()))
    for path in product_paths:
        slots.append(("product", read_volume_image(ws, path)))
    if logo is not None:
        slots.append(("logo", await logo.read()))
    elif kit and kit.logo_path:
        slots.append(("logo", read_logo(request, kit.logo_path)))
    if style_ref is not None:
        slots.append(("style", await style_ref.read()))
    elif style_ref_path:
        slots.append(("style", read_volume_image(ws, style_ref_path)))
    if not slots:
        raise HTTPException(400, "Add at least one image: a product, background, logo or style reference")
    if len(slots) > MAX_INPUT_IMAGES:
        raise HTTPException(400, f"At most {MAX_INPUT_IMAGES} reference images")

    prompt = _compose_prompt(
        fmt, headline=headline, subheadline=subheadline, cta=cta, art_direction=art_direction, kit=kit,
    )
    labels = [f"Image {i} — {_COMPOSE_ROLES[role]}" for i, (role, _) in enumerate(slots, start=1)]
    tool_overrides = {
        "quality": quality, "size": fmt["size"], "output_format": output_format, "background": "auto",
    }
    if complexity:
        tool_overrides["complexity"] = complexity
    tool_meta = {
        "image_model": effective_model, "size": fmt["size"], "quality": quality,
        "output_format": output_format, "background": "auto",
    }
    criteria = "\n\n".join(part for part in ((kit.body.strip() if kit else ""), _COMPOSE_CHECKS) if part)
    title = f"{headline.strip() or 'Compose'} · {fmt['label']}"

    events = get_image_gen(request, image_model).stream_edit(
        prompt, [data for _, data in slots], labels=labels, n=n, persist=False, **tool_overrides,
    )
    return EventSourceResponse(_relay_events(
        request, events, ext=_OUTPUT_FORMAT_TO_EXT.get(output_format, ".png"), folder=folder,
        mode="compose", prompt_for=lambda _: prompt, meta_for=lambda _: tool_meta,
        criteria=criteria, title_for=lambda _: title,
    ))


# --- Adapt: re-lay out one finished creative for several formats -------------------------

_ADAPT_PROMPT = (
    "Re-lay out this exact creative for a {w}×{h} {label} ({ratio}) format. Keep every text "
    "element (same words, spelling and typeface feel), the logo, the product and the colours "
    "identical. Extend or recompose the background to fit. Never crop or distort text, logo or "
    "product."
)


@router.post("/adapt", operation_id="adaptToFormats")
async def adapt_to_formats(
    request: Request,
    formats: list[str] = Form(...),
    source: UploadFile | None = Form(None),
    source_batch_id: str = Form(""),
    source_image_id: int = Form(1),
    folder: str = Form("default"),
    quality: str = Form("auto"),
    output_format: str = Form("png"),
    image_model: str = Form(""),
    criteria: str = Form(""),
):
    """Adapt a finished creative to several marketing formats in one go: one edit per format,
    run concurrently and streamed as one SSE stream whose event index is the format's position
    in `formats`. The source is an upload or a gallery image (`source_batch_id` / `source_image_id`)."""
    keys = list(dict.fromkeys(formats))  # de-dupe, keep order
    if not keys:
        raise HTTPException(400, "Pick at least one format")
    presets = [_format_preset(key) for key in keys]
    image_model = image_model or request.app.state.config.image_model
    # A re-layout is a focused edit; low complexity keeps the creative from drifting.
    complexity = "low" if MODEL_PRESETS.get(image_model, {}).get("supports_complexity") else ""
    validate_raster_format(output_format)
    effective_model = image_model
    for fmt in presets:
        effective_model = validate_tool_request(image_model, "auto", quality, fmt["size"], complexity)

    if source is not None:
        source_bytes = await source.read()
        source_name = (source.filename or "creative").rsplit(".", 1)[0]
    elif source_batch_id:
        rows = _pg_fetch(
            request.app.state.db_pool,
            "SELECT volume_path, image_name FROM generated_images WHERE batch_id = %s AND id = %s",
            (source_batch_id, source_image_id),
        )
        if not rows or not rows[0].get("volume_path"):
            raise HTTPException(404, "Source image not found")
        source_bytes = read_volume_image(_get_user_ws_from_request(request), rows[0]["volume_path"])
        source_name = (rows[0].get("image_name") or "creative").replace("_", " ")
    else:
        raise HTTPException(400, "Provide a source image upload or source_batch_id")

    image_gen = get_image_gen(request, image_model)
    prompts, metas, streams = [], [], []
    for fmt in presets:
        w, h = fmt["size"].split("x")
        prompts.append(_ADAPT_PROMPT.format(w=w, h=h, label=fmt["label"].lower(), ratio=fmt["ratio"]))
        metas.append({
            "image_model": effective_model, "size": fmt["size"], "quality": quality,
            "output_format": output_format, "background": "auto",
        })
        overrides = {
            "quality": quality, "size": fmt["size"], "output_format": output_format, "background": "auto",
        }
        if complexity:
            overrides["complexity"] = complexity
        streams.append(image_gen.stream_edit(prompts[-1], [source_bytes], n=1, persist=False, **overrides))

    return EventSourceResponse(_relay_events(
        request, _merge_streams(streams), ext=_OUTPUT_FORMAT_TO_EXT.get(output_format, ".png"),
        folder=folder, mode="adapt", prompt_for=lambda i: prompts[i], meta_for=lambda i: metas[i],
        criteria=criteria.strip() or None,
        title_for=lambda i: f"{source_name} · {presets[i]['label']}",
    ))


# --- Vector (SVG) ------------------------------------------------------------------------

_SVG_NOT_SCORED = "Vector (SVG) — not scored: the judges and SigLIP search work on raster images."


def _save_svg(request: Request, svg: str, prompt: str, folder: str, image_model: str, quality: str) -> str:
    """Persist a vector result and return its batch_id. SVGs skip the raster pipeline
    (thumbnail, SigLIP embedding, judges): the SVG is its own thumbnail and the row is
    marked as not scored."""
    cfg = request.app.state.config
    pool: ConnectionPool = request.app.state.db_pool
    ws = _get_user_ws_from_request(request)
    batch_id = str(uuid.uuid4())[:8]
    stem = _slug_from_prompt(prompt)
    path = f"{cfg.vision_volume}/{folder}/{batch_id}/{stem}.svg"
    ws.files.upload(path, BytesIO(svg.encode("utf-8")), overwrite=True)
    if pool:
        _pg_execute(pool, "INSERT INTO folders (name) VALUES (%s) ON CONFLICT DO NOTHING", (folder,))
        _pg_execute(
            pool,
            """INSERT INTO batch_runs
               (batch_id, batch_name, batch_mode, status, created_at,
                total_images, successful_images, output_volume_path, folder,
                image_model, size, quality, output_format, background)
               VALUES (%s, %s, 'vector', 'completed', NOW(), 1, 1, %s, %s, %s, 'auto', %s, 'svg', 'auto')""",
            (batch_id, prompt[:100], f"{cfg.vision_volume}/{folder}/{batch_id}", folder,
             image_model, quality),
        )
        _pg_execute(
            pool,
            """INSERT INTO generated_images
               (id, batch_id, image_name, prompt, status, volume_path, thumbnail_path,
                image_model, size, description, evaluation)
               VALUES (1, %s, %s, %s, 'success', %s, %s, %s, 'svg', %s, %s)""",
            (batch_id, stem, prompt, path, path, image_model, prompt, _SVG_NOT_SCORED),
        )
    return batch_id


@router.post("/generate-svg", operation_id="generateSvg")
async def generate_svg(
    request: Request,
    prompt: str = Form(...),
    folder: str = Form("default"),
    quality: str = Form("auto"),
    image_model: str = Form(""),
):
    """Generate one vector graphic (icon, illustration, brand mark) as editable SVG. Not
    streamed — SVG output can't stream — and typically takes about a minute."""
    svg_models = [m for m in enabled_image_models() if MODEL_PRESETS[m]["supports_svg"]]
    image_model = image_model or (svg_models[0] if svg_models else "")
    if image_model not in svg_models:
        raise HTTPException(400, f"SVG needs one of: {', '.join(svg_models) or 'no enabled model'}")
    validate_tool_request(image_model, "auto", quality, "auto")
    try:
        svg = await get_image_gen(request, image_model).generate_svg(prompt, quality=quality)
    except ValueError as exc:
        raise HTTPException(502, f"Vector generation failed: {exc}")
    batch_id = _save_svg(request, svg, prompt, folder, image_model, quality)
    return {"batch_id": batch_id, "image_id": 1, "svg": svg}
