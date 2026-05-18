"""Gallery CRUD — unified view over generated_images + batch_runs."""
from __future__ import annotations

import asyncio
import json
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from image_gen import ImageAnalyzer, ImageGen
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sse_starlette.sse import EventSourceResponse

from ..core import Dependencies
from ..core._background import spawn_bg
from ..core._image_gen_dep import get_sp_token
from ..models import FolderCreate, FolderOut, GeneratedImageOut

router = APIRouter(tags=["gallery"])


def _pg_fetch(pool: ConnectionPool, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
    return [dict(r) for r in rows]


def _pg_execute(pool: ConnectionPool, sql: str, params: tuple = ()) -> None:
    with pool.connection() as conn:
        conn.execute(sql, params)
        conn.commit()


# --- Images (unified: batch + single) ---

_GALLERY_SELECT = """
    SELECT g.id, g.batch_id, g.image_name, g.prompt, g.status,
           g.error_message, g.volume_path, g.variation_label,
           g.input_image_path, g.description, g.tags, g.thumbnail_path,
           g.evaluation, g.metrics, g.missing_elements, g.safety_flags,
           g.brand_conflicts, g.improved_prompt, g.criteria_evaluation,
           br.batch_mode, br.batch_name, br.folder, br.created_at
    FROM generated_images g
    JOIN batch_runs br ON br.batch_id = g.batch_id
    WHERE g.status = 'success'
"""


@router.get("/gallery", response_model=list[GeneratedImageOut], operation_id="listGalleryImages")
def list_images(
    db: Dependencies.DB,
    folder: str | None = None,
    batch_id: str | None = None,
    mode: str | None = None,
    page: int = 1,
    limit: int = 50,
):
    offset = (page - 1) * limit
    where = []
    params: list = []

    if folder:
        where.append("br.folder = %s")
        params.append(folder)
    if batch_id:
        where.append("g.batch_id = %s")
        params.append(batch_id)
    if mode == "single":
        where.append("br.batch_mode IN ('single', 'edit')")
    elif mode:
        where.append("br.batch_mode = %s")
        params.append(mode)

    extra_where = (" AND " + " AND ".join(where)) if where else ""
    sql = f"{_GALLERY_SELECT} {extra_where} ORDER BY br.created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = _pg_fetch(db, sql, tuple(params))
    return [_row_to_gen_image(r) for r in rows]


@router.delete("/gallery/{batch_id}/{image_id}", operation_id="deleteGalleryImage")
def delete_image(batch_id: str, image_id: int, db: Dependencies.DB, ws: Dependencies.UserClient):
    rows = _pg_fetch(
        db,
        "SELECT g.volume_path, g.thumbnail_path, br.batch_mode FROM generated_images g JOIN batch_runs br ON br.batch_id = g.batch_id WHERE g.batch_id = %s AND g.id = %s",
        (batch_id, image_id),
    )
    if not rows:
        raise HTTPException(404, "Image not found")

    image = rows[0]

    # Track parent dirs of every file we delete so we can sweep them after.
    parent_dirs: set[str] = set()
    for path_field in ("volume_path", "thumbnail_path"):
        path = image.get(path_field)
        if path:
            try:
                ws.files.delete(path)
            except Exception:
                pass
            parent = path.rsplit("/", 1)[0]
            if parent.startswith("/Volumes/"):
                parent_dirs.add(parent)

    _pg_execute(db, "DELETE FROM generated_images WHERE batch_id = %s AND id = %s", (batch_id, image_id))

    remaining = _pg_fetch(db, "SELECT COUNT(*) AS cnt FROM generated_images WHERE batch_id = %s", (batch_id,))
    remaining_count = remaining[0]["cnt"] if remaining else 0

    if remaining_count == 0 and image.get("batch_mode") in ("single", "edit"):
        _pg_execute(db, "DELETE FROM batch_runs WHERE batch_id = %s", (batch_id,))
    else:
        successful = _pg_fetch(db, "SELECT COUNT(*) AS cnt FROM generated_images WHERE batch_id = %s AND status = 'success'", (batch_id,))
        _pg_execute(
            db,
            "UPDATE batch_runs SET total_images = %s, successful_images = %s WHERE batch_id = %s",
            (remaining_count, successful[0]["cnt"] if successful else 0, batch_id),
        )

    # Sweep the parent dirs — `delete_directory` only succeeds when empty, so this
    # is a no-op for multi-image batches that still have siblings.
    for parent in parent_dirs:
        try:
            ws.files.delete_directory(parent)
        except Exception:
            pass

    return {"deleted": True}


@router.get("/gallery/{batch_id}/{image_id}/file", operation_id="getGalleryImageFile")
def get_image_file(batch_id: str, image_id: int, db: Dependencies.DB, ws: Dependencies.UserClient):
    rows = _pg_fetch(
        db, "SELECT volume_path FROM generated_images WHERE batch_id = %s AND id = %s", (batch_id, image_id)
    )
    if not rows or not rows[0].get("volume_path"):
        raise HTTPException(404, "Image file not found")

    try:
        resp = ws.files.download(rows[0]["volume_path"])
        content = resp.contents.read()
    except Exception as e:
        raise HTTPException(404, f"Could not read image: {e}")

    path = rows[0]["volume_path"]
    media_type = "image/png"
    if path.endswith(".jpg") or path.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif path.endswith(".webp"):
        media_type = "image/webp"
    return Response(content=content, media_type=media_type)


@router.get("/gallery/{batch_id}/{image_id}/thumbnail", operation_id="getGalleryThumbnail")
def get_image_thumbnail(batch_id: str, image_id: int, db: Dependencies.DB, ws: Dependencies.UserClient):
    rows = _pg_fetch(
        db,
        "SELECT thumbnail_path, volume_path FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    if not rows:
        raise HTTPException(404, "Image not found")

    path = rows[0].get("thumbnail_path") or rows[0].get("volume_path")
    if not path:
        raise HTTPException(404, "No image file available")

    try:
        resp = ws.files.download(path)
        content = resp.contents.read()
    except Exception as e:
        raise HTTPException(404, f"Could not read thumbnail: {e}")

    media_type = "image/webp" if path.endswith(".webp") else "image/png"
    return Response(content=content, media_type=media_type)


# --- Folders ---

@router.get("/folders", response_model=list[FolderOut], operation_id="listFolders")
def list_folders(db: Dependencies.DB):
    rows = _pg_fetch(
        db,
        """SELECT f.id, f.name, f.created_at,
                  COUNT(g.id) AS image_count
           FROM folders f
           LEFT JOIN batch_runs br ON br.folder = f.name AND br.batch_mode IN ('single', 'edit')
           LEFT JOIN generated_images g ON g.batch_id = br.batch_id AND g.status = 'success'
           GROUP BY f.id, f.name, f.created_at
           ORDER BY f.name""",
    )
    return [FolderOut(**r) for r in rows]


@router.post("/folders", response_model=FolderOut, operation_id="createFolder")
def create_folder(body: FolderCreate, db: Dependencies.DB):
    name = body.name.strip().lower().replace(" ", "_")
    if not name:
        raise HTTPException(400, "Folder name cannot be empty")
    _pg_execute(
        db,
        "INSERT INTO folders (name) VALUES (%s) ON CONFLICT DO NOTHING",
        (name,),
    )
    rows = _pg_fetch(db, "SELECT id, name, created_at FROM folders WHERE name = %s", (name,))
    return FolderOut(id=rows[0]["id"], name=rows[0]["name"], created_at=rows[0]["created_at"])


@router.delete("/folders/{name}", operation_id="deleteFolder")
def delete_folder(name: str, db: Dependencies.DB, ws: Dependencies.UserClient):
    """Hard-delete a folder: remove every batch in it, every generated_images +
    image_versions row (via FK cascade), and every Volume file referenced by those
    rows. SQL goes first (transactionally safe — a dead row pointing at a missing
    file is worse than an orphan file the admin can sweep). File deletes are
    best-effort and do not abort the operation if a single one fails.
    """
    if name == "default":
        raise HTTPException(400, "Cannot delete the default folder")

    # Step 1 — collect every file the folder references before we drop the rows.
    files = _pg_fetch(
        db,
        """SELECT g.volume_path, g.thumbnail_path
           FROM generated_images g
           JOIN batch_runs br ON br.batch_id = g.batch_id
           WHERE br.folder = %s""",
        (name,),
    )
    version_files = _pg_fetch(
        db,
        """SELECT iv.volume_path
           FROM image_versions iv
           JOIN batch_runs br ON br.batch_id = iv.batch_id
           WHERE br.folder = %s""",
        (name,),
    )

    paths: list[str] = []
    for r in files:
        if r.get("volume_path"):
            paths.append(r["volume_path"])
        if r.get("thumbnail_path"):
            paths.append(r["thumbnail_path"])
    for r in version_files:
        if r.get("volume_path"):
            paths.append(r["volume_path"])

    # Step 2 — drop the rows. FK ON DELETE CASCADE on generated_images / image_versions
    # means deleting batch_runs takes everything with it.
    _pg_execute(db, "DELETE FROM batch_runs WHERE folder = %s", (name,))
    _pg_execute(db, "DELETE FROM folders WHERE name = %s", (name,))

    # Step 3 — best-effort sweep. Orphan files are recoverable; dead rows aren't.
    deleted = failed = 0
    for p in paths:
        try:
            ws.files.delete(p)
            deleted += 1
        except Exception:
            failed += 1
    return {
        "deleted": True,
        "rows_deleted": len(files),
        "files_deleted": deleted,
        "files_failed": failed,
    }


@router.post("/gallery/analyze", operation_id="analyzeGalleryImages")
async def analyze_images(
    request: Request,
    batch_id: str = Form(...),
):
    """Backfill description, tags, thumbnails, and full eval for batch images."""
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")

    cfg = request.app.state.config
    vw = request.app.state.vision_workspace
    # SP-bound — see core/_image_gen_dep._get_user_token for the rationale.
    token = get_sp_token(request)
    openai_client = vw.openai_for_token(token) if token else vw.openai
    analyzer = ImageAnalyzer(workspace=vw, model=cfg.model_name, openai_client=openai_client)

    # File downloads use the SP — see _defaults._get_user_ws for why OBO is bypassed
    # for Volume operations.
    ws = request.app.state.workspace_client

    rows = _pg_fetch(
        pool,
        """SELECT batch_id, id, prompt, volume_path
           FROM generated_images
           WHERE batch_id = %s
             AND status = 'success'
             AND (description IS NULL OR metrics IS NULL OR embedding IS NULL)""",
        (batch_id,),
    )

    if not rows:
        raise HTTPException(200, "All images already analyzed and evaluated")

    async def event_generator():
        total = len(rows)
        analyzed = 0

        for row in rows:
            volume_path = row.get("volume_path")
            if not volume_path:
                analyzed += 1
                continue

            try:
                resp = ws.files.download(volume_path)
                image_bytes = resp.contents.read()

                analyze_task = asyncio.create_task(analyzer.analyze(image_bytes, gen_prompt=row.get("prompt")))
                embed_task = asyncio.create_task(asyncio.to_thread(vw.embed_image, image_bytes))
                analysis = await analyze_task
                try:
                    embedding = await embed_task
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning("Embed failed for %s/%s: %s", row["batch_id"], row["id"], exc)
                    embedding = None

                thumbnail_bytes = ImageGen.make_thumbnail_bytes(image_bytes)
                thumb_dir = volume_path.rsplit("/", 1)[0]
                thumbnail_path = f"{thumb_dir}/thumb_{row['id']}.webp"
                ws.files.upload(thumbnail_path, BytesIO(thumbnail_bytes), overwrite=True)

                metrics_json = json.dumps(analysis.metrics.model_dump())
                _pg_execute(
                    pool,
                    """UPDATE generated_images SET
                          description = %s,
                          tags = %s::jsonb,
                          thumbnail_path = %s,
                          evaluation = %s,
                          metrics = %s::jsonb,
                          missing_elements = %s::jsonb,
                          safety_flags = %s::jsonb,
                          brand_conflicts = %s::jsonb,
                          improved_prompt = %s,
                          criteria_evaluation = %s,
                          embedding = COALESCE(%s::vector, embedding)
                       WHERE batch_id = %s AND id = %s""",
                    (
                        analysis.description,
                        json.dumps(analysis.tags),
                        thumbnail_path,
                        analysis.evaluation,
                        metrics_json,
                        json.dumps(analysis.missing_or_wrong_elements),
                        json.dumps(analysis.safety_flags),
                        json.dumps(analysis.brand_conflicts),
                        analysis.improved_prompt,
                        analysis.criteria_evaluation,
                        embedding,
                        row["batch_id"],
                        row["id"],
                    ),
                )

                analyzed += 1
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "analyzed": analyzed,
                        "total": total,
                        "current_id": row["id"],
                        "description": analysis.description,
                        "metrics": analysis.metrics.model_dump(),
                    }),
                }

            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Analysis failed for %s/%s: %s", row["batch_id"], row["id"], e, exc_info=True)
                analyzed += 1
                yield {
                    "event": "progress",
                    "data": json.dumps({"analyzed": analyzed, "total": total, "current_id": row["id"], "error": str(e)}),
                }

        yield {"event": "complete", "data": json.dumps({"analyzed": analyzed, "total": total})}

    return EventSourceResponse(event_generator())


@router.post(
    "/gallery/{batch_id}/{image_id}/analyze",
    operation_id="analyzeSingleImage",
)
async def analyze_single_image(
    request: Request,
    batch_id: str,
    image_id: int,
):
    """Re-run analyzer + embed for one image. Used as a manual fallback when
    Phase 2 didn't fire or the analyzer 429'd. Synchronous (~5–10s) so the
    caller can await it directly and refresh the dialog.
    """
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")

    rows = _pg_fetch(
        pool,
        "SELECT batch_id, id, prompt, volume_path FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    if not rows:
        raise HTTPException(404, "Image not found")
    row = rows[0]
    volume_path = row.get("volume_path")
    if not volume_path:
        raise HTTPException(409, "Image has no volume_path; cannot analyze")

    cfg = request.app.state.config
    vw = request.app.state.vision_workspace
    token = get_sp_token(request)
    openai_client = vw.openai_for_token(token) if token else vw.openai
    analyzer = ImageAnalyzer(workspace=vw, model=cfg.model_name, openai_client=openai_client)

    ws = request.app.state.workspace_client
    try:
        resp = ws.files.download(volume_path)
        image_bytes = resp.contents.read()
    except Exception as exc:
        raise HTTPException(500, f"Failed to download image: {exc}") from exc

    analyze_task = asyncio.create_task(analyzer.analyze(image_bytes, gen_prompt=row.get("prompt")))
    embed_task = asyncio.create_task(asyncio.to_thread(vw.embed_image, image_bytes))

    analysis = embedding = None
    try:
        analysis = await analyze_task
    except Exception as exc:
        raise HTTPException(502, f"Analyzer call failed: {exc}") from exc
    try:
        embedding = await embed_task
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Embed failed for %s/%s: %s", batch_id, image_id, exc)

    _pg_execute(
        pool,
        """UPDATE generated_images SET
              description = %s,
              tags = %s::jsonb,
              evaluation = %s,
              metrics = %s::jsonb,
              missing_elements = %s::jsonb,
              safety_flags = %s::jsonb,
              brand_conflicts = %s::jsonb,
              improved_prompt = %s,
              criteria_evaluation = %s,
              embedding = COALESCE(%s::vector, embedding)
           WHERE batch_id = %s AND id = %s""",
        (
            analysis.description,
            json.dumps(analysis.tags),
            analysis.evaluation,
            json.dumps(analysis.metrics.model_dump()),
            json.dumps(analysis.missing_or_wrong_elements),
            json.dumps(analysis.safety_flags),
            json.dumps(analysis.brand_conflicts),
            analysis.improved_prompt,
            analysis.criteria_evaluation,
            embedding,
            batch_id,
            image_id,
        ),
    )

    refreshed = _pg_fetch(
        pool,
        "SELECT * FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    return _row_to_gen_image(refreshed[0])


def _row_to_gen_image(row: dict) -> GeneratedImageOut:
    def _jsonb_list(value) -> list:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return json.loads(value) or []
            except Exception:
                return []
        return value

    metrics = row.get("metrics")
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = None

    return GeneratedImageOut(
        id=row.get("id"),
        batch_id=row["batch_id"],
        image_name=row.get("image_name"),
        prompt=row.get("prompt"),
        status=row.get("status"),
        error_message=row.get("error_message"),
        volume_path=row.get("volume_path"),
        variation_label=row.get("variation_label"),
        input_image_path=row.get("input_image_path"),
        description=row.get("description"),
        tags=_jsonb_list(row.get("tags")),
        folder=row.get("folder"),
        thumbnail_path=row.get("thumbnail_path"),
        evaluation=row.get("evaluation"),
        metrics=metrics,
        missing_elements=_jsonb_list(row.get("missing_elements")),
        safety_flags=_jsonb_list(row.get("safety_flags")),
        brand_conflicts=_jsonb_list(row.get("brand_conflicts")),
        improved_prompt=row.get("improved_prompt"),
        criteria_evaluation=row.get("criteria_evaluation"),
    )


# --- Import (bulk-upload local images, synthesize prompt, analyze + embed) ---


_IMPORT_PLACEHOLDER_PROMPT = "(synthesizing prompt…)"


def _ext_from_filename(name: str) -> str:
    name = name.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if name.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".png"


async def _import_one_phase2(
    request: Request,
    image_bytes: bytes,
    batch_id: str,
    folder: str,
    filename_stem: str,
) -> None:
    """Background task: synthesize a prompt via gen.rewrite (mode 3 — image + instructions),
    then run the analyzer + embedding in parallel and UPDATE the row.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        cfg = request.app.state.config
        pool: ConnectionPool = request.app.state.db_pool
        if not pool:
            return

        vw = request.app.state.vision_workspace
        # Per-request OBO-bound clients are gone by now (the SSE response closed); fall back to
        # an SP token. Mint a fresh one — SP/OAuth tokens have a ~1h TTL and a stale value
        # would surface here as "Invalid Token" from the analyzer's Responses call.
        sp_token = get_sp_token(request)
        oai = vw.openai_for_token(sp_token) if sp_token else vw.openai

        image_gen = ImageGen(
            workspace=vw,
            output_root=cfg.output_volume,
            reasoning_model=cfg.model_name,
            image_model=cfg.image_model,
            openai_client=oai,
        )

        # Mode 3 of rewrite: synthesize a faithful text prompt from the image.
        try:
            prompt = await image_gen.rewrite(
                images=[image_bytes],
                instructions="Analyze the image and produce a single text prompt that reproduces it as accurately as possible. Capture subject, composition, style, lighting, palette, and notable details. Return only the prompt.",
            )
        except Exception as exc:
            log.warning("Import rewrite failed for %s/1: %s", batch_id, exc)
            prompt = filename_stem  # last-resort fallback so the row has *something*

        analyzer = ImageAnalyzer(workspace=vw, model=cfg.model_name, openai_client=oai)
        analyze_task = asyncio.create_task(analyzer.analyze(image_bytes, gen_prompt=prompt))
        embed_task = asyncio.create_task(asyncio.to_thread(vw.embed_image, image_bytes))
        analysis = embedding = None
        try:
            analysis = await analyze_task
        except Exception as exc:
            log.warning("Import analyze failed for %s/1: %s", batch_id, exc)
        try:
            embedding = await embed_task
        except Exception as exc:
            log.warning("Import embed failed for %s/1: %s", batch_id, exc)

        if analysis is not None and embedding is not None:
            _pg_execute(
                pool,
                """UPDATE generated_images SET
                      prompt = %s, description = %s, tags = %s::jsonb,
                      evaluation = %s, metrics = %s::jsonb,
                      missing_elements = %s::jsonb, safety_flags = %s::jsonb,
                      brand_conflicts = %s::jsonb, improved_prompt = %s,
                      embedding = %s
                   WHERE batch_id = %s AND id = 1""",
                (
                    prompt, analysis.description, json.dumps(analysis.tags),
                    analysis.evaluation, json.dumps(analysis.metrics.model_dump()),
                    json.dumps(analysis.missing_or_wrong_elements), json.dumps(analysis.safety_flags),
                    json.dumps(analysis.brand_conflicts), analysis.improved_prompt,
                    embedding, batch_id,
                ),
            )
        elif analysis is not None:
            _pg_execute(
                pool,
                """UPDATE generated_images SET
                      prompt = %s, description = %s, tags = %s::jsonb,
                      evaluation = %s, metrics = %s::jsonb,
                      missing_elements = %s::jsonb, safety_flags = %s::jsonb,
                      brand_conflicts = %s::jsonb, improved_prompt = %s
                   WHERE batch_id = %s AND id = 1""",
                (
                    prompt, analysis.description, json.dumps(analysis.tags),
                    analysis.evaluation, json.dumps(analysis.metrics.model_dump()),
                    json.dumps(analysis.missing_or_wrong_elements), json.dumps(analysis.safety_flags),
                    json.dumps(analysis.brand_conflicts), analysis.improved_prompt,
                    batch_id,
                ),
            )
        else:
            # Even if both failed, at least swap the placeholder prompt for the rewritten one.
            _pg_execute(
                pool,
                "UPDATE generated_images SET prompt = %s WHERE batch_id = %s AND id = 1",
                (prompt, batch_id),
            )
    except Exception as exc:
        log.error("Import Phase 2 failed for %s: %s", batch_id, exc, exc_info=True)


@router.post("/import", operation_id="importImages")
async def import_images(
    request: Request,
    folder: str = Form("default"),
    images: list[UploadFile] = Form(default=[]),
):
    """Bulk-import local images into a folder. Phase 1 uploads each file +
    thumbnail to UC Volume and INSERTs a generated_images row with a placeholder
    prompt so it appears in the gallery immediately. Phase 2 (per row,
    fire-and-forget) synthesizes a prompt via ImageGen.rewrite (mode 3) and
    runs the analyzer + embedding, then UPDATEs the row.
    """
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    if not images:
        raise HTTPException(400, "No images uploaded")

    cfg = request.app.state.config
    # File uploads use the SP — see _defaults._get_user_ws for why OBO is bypassed
    # for Volume operations.
    user_ws = request.app.state.workspace_client

    # Read uploads now — UploadFile streams close once the request scope exits, but
    # we need the bytes inside background tasks. Cap each to 25 MB to keep memory sane.
    payload: list[tuple[str, bytes]] = []
    for upload in images:
        data = await upload.read()
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, f"{upload.filename}: file exceeds 25 MB limit")
        payload.append((upload.filename or "image", data))

    _pg_execute(pool, "INSERT INTO folders (name) VALUES (%s) ON CONFLICT DO NOTHING", (folder,))

    async def event_generator():
        import re
        import uuid
        total = len(payload)
        for i, (orig_name, data) in enumerate(payload):
            try:
                stem = re.sub(r"[^a-z0-9]+", "_", orig_name.rsplit(".", 1)[0].lower()).strip("_") or "image"
                stem = stem[:40]
                ext = _ext_from_filename(orig_name)
                batch_id = uuid.uuid4().hex[:8]
                filename = f"{stem}{ext}"
                volume_path = f"{cfg.vision_volume}/{folder}/{batch_id}/{filename}"
                thumb_path = f"{cfg.vision_volume}/{folder}/{batch_id}/thumb.webp"

                user_ws.files.upload(volume_path, BytesIO(data), overwrite=True)
                user_ws.files.upload(thumb_path, BytesIO(ImageGen.make_thumbnail_bytes(data)), overwrite=True)

                _pg_execute(
                    pool,
                    """INSERT INTO batch_runs
                       (batch_id, batch_name, batch_mode, status, created_at,
                        total_images, successful_images, output_volume_path, folder)
                       VALUES (%s, %s, 'single', 'completed', NOW(), 1, 1, %s, %s)""",
                    (batch_id, f"Imported: {orig_name[:90]}", f"{cfg.vision_volume}/{folder}/{batch_id}", folder),
                )
                _pg_execute(
                    pool,
                    """INSERT INTO generated_images
                       (id, batch_id, image_name, prompt, status, volume_path, thumbnail_path)
                       VALUES (1, %s, %s, %s, 'success', %s, %s)""",
                    (batch_id, stem, _IMPORT_PLACEHOLDER_PROMPT, volume_path, thumb_path),
                )

                # Fire and forget Phase 2 — spawn_bg keeps a strong ref so the
                # task isn't GC'd before the analyzer call resolves.
                spawn_bg(_import_one_phase2(request, data, batch_id, folder, stem))

                yield {
                    "event": "progress",
                    "data": json.dumps({"index": i + 1, "total": total, "batch_id": batch_id, "name": orig_name}),
                }
            except Exception as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({"index": i + 1, "total": total, "name": orig_name, "error": str(exc)}),
                }

        yield {"event": "complete", "data": json.dumps({"count": total})}

    return EventSourceResponse(event_generator())
