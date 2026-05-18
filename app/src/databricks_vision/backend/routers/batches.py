import base64
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..core import Dependencies
from ..core._image_validation import validate_size
from ..models import (
    BatchCreate,
    BatchDetailOut,
    BatchRunOut,
    GeneratedImageOut,
    ImageVersionOut,
    RegenerateRequest,
    RegenerateResponse,
)

router = APIRouter(prefix="/batches", tags=["batches"])


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


@router.get("", response_model=list[BatchRunOut], operation_id="listBatches")
def list_batches(db: Dependencies.DB):
    rows = _pg_fetch(db, """
        SELECT br.*,
               COUNT(g.id) AS total_images,
               COUNT(g.id) FILTER (WHERE g.status = 'success') AS successful_images
        FROM batch_runs br
        LEFT JOIN generated_images g ON g.batch_id = br.batch_id
        GROUP BY br.batch_id
        ORDER BY br.created_at DESC
    """)
    return [BatchRunOut(**r) for r in rows]


@router.post("", response_model=BatchRunOut, operation_id="createBatch")
def create_batch(
    body: BatchCreate,
    user_ws: Dependencies.UserClient,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    db: Dependencies.DB,
):
    if body.batch_mode == "variations":
        if not body.source_image_path.startswith("/Volumes/"):
            raise HTTPException(400, "source_image_path must start with /Volumes/")
        if len(body.variations) < 2:
            raise HTTPException(400, "At least 2 variations are required")
    else:
        if not body.input_volume_path.startswith("/Volumes/"):
            raise HTTPException(400, "input_volume_path must start with /Volumes/")

    size = body.size or "1024x1024"
    background = body.background or "opaque"
    validate_size(size, transparent=(background == "transparent"))

    batch_id = str(uuid.uuid4())[:8]
    try:
        user_email = user_ws.current_user.me().user_name or "unknown"
    except Exception as e:
        raise HTTPException(500, f"Failed to get current user: {e}")

    now = datetime.now(timezone.utc)
    ref_path = body.reference_image_path or ""
    output_path = f"{config.output_volume}/{batch_id}"

    if not config.batch_gen_job_id:
        raise HTTPException(
            503,
            "batch-gen-job id not resolved — the app resource list is missing it "
            "(check databricks.yml + redeploy) or Apps API access failed",
        )

    batch_name = body.batch_name or ""
    quality = body.quality or "low"
    # Transparent BG forces gpt-image-1.5 (only model that supports transparency),
    # mirroring image_gen.ImageGen._build_tools.
    image_model = "gpt-image-1.5" if background == "transparent" else (body.image_model or "gpt-image-2")
    output_format = body.output_format or "png"
    style_guideline_id = body.style_guideline_id

    job_params = {
        "batch_id": batch_id,
        "batch_name": batch_name,
        "reference_image_path": ref_path,
        "created_by": user_email,
        "batch_mode": body.batch_mode,
        "size": size,
        "quality": quality,
        "image_model": image_model,
        "output_format": output_format,
        "background": background,
        "style_guideline_id": str(style_guideline_id) if style_guideline_id is not None else "",
    }
    if body.batch_mode == "variations":
        job_params["input_volume_path"] = ""
        job_params["source_image_path"] = body.source_image_path
        job_params["prompt_template"] = ""
        job_params["variations_json"] = json.dumps(
            [{"label": v.label, "prompt": v.prompt} for v in body.variations]
        )
    else:
        job_params["input_volume_path"] = body.input_volume_path
        job_params["source_image_path"] = ""
        job_params["prompt_template"] = body.prompt_template
        job_params["variations_json"] = "[]"

    try:
        run = ws.jobs.run_now(
            job_id=config.batch_gen_job_id,
            job_parameters=job_params,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to trigger job: {e}")

    input_path = body.input_volume_path if body.batch_mode == "multi_image" else ""
    _pg_execute(
        db,
        """INSERT INTO batch_runs
           (batch_id, batch_name, batch_mode, input_volume_path, source_image_path,
            reference_image_path, prompt_template, size, quality, image_model,
            output_format, background, style_guideline_id,
            status, created_at, created_by, output_volume_path, job_run_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   'running', %s, %s, %s, %s)""",
        (batch_id, batch_name, body.batch_mode, input_path, body.source_image_path or "",
         ref_path, body.prompt_template or "", size, quality, image_model,
         output_format, background, style_guideline_id,
         now, user_email, output_path, run.run_id),
    )

    return BatchRunOut(
        batch_id=batch_id,
        batch_name=batch_name,
        batch_mode=body.batch_mode,
        input_volume_path=input_path,
        source_image_path=body.source_image_path or "",
        reference_image_path=ref_path,
        prompt_template=body.prompt_template or "",
        size=size,
        quality=quality,
        image_model=image_model,
        output_format=output_format,
        background=background,
        style_guideline_id=style_guideline_id,
        status="running",
        created_at=now,
        created_by=user_email,
        job_run_id=run.run_id,
        output_volume_path=output_path,
    )


@router.get("/{batch_id}", response_model=BatchDetailOut, operation_id="getBatchDetail")
def get_batch_detail(batch_id: str, db: Dependencies.DB):
    batches = _pg_fetch(db, "SELECT * FROM batch_runs WHERE batch_id = %s", (batch_id,))
    if not batches:
        raise HTTPException(404, "Batch not found")

    images = _pg_fetch(
        db,
        """SELECT g.id, g.batch_id, g.image_name, g.prompt, g.status,
                  g.error_message, g.volume_path, g.variation_label,
                  g.input_image_path, g.description, g.tags, g.thumbnail_path,
                  g.evaluation, g.metrics, g.missing_elements, g.safety_flags,
                  g.brand_conflicts, g.improved_prompt, g.criteria_evaluation,
                  COALESCE(v.max_ver, 0) AS version_count
           FROM generated_images g
           LEFT JOIN (
               SELECT batch_id, image_id, MAX(version) AS max_ver
               FROM image_versions
               GROUP BY batch_id, image_id
           ) v ON v.batch_id = g.batch_id AND v.image_id = g.id
           WHERE g.batch_id = %s
           ORDER BY g.image_name""",
        (batch_id,),
    )

    def _coerce(img: dict) -> dict:
        out = dict(img)
        # JSONB columns can come back as str on some drivers; list-typed JSONBs may also
        # be NULL on rows analysed before the eval feature — normalise to empty list.
        for col in ("tags", "missing_elements", "safety_flags", "brand_conflicts"):
            v = out.get(col)
            if v is None:
                out[col] = []
            elif isinstance(v, str):
                try:
                    out[col] = json.loads(v) or []
                except Exception:
                    out[col] = []
        m = out.get("metrics")
        if isinstance(m, str):
            try:
                out["metrics"] = json.loads(m)
            except Exception:
                out["metrics"] = None
        return out

    return BatchDetailOut(
        batch=BatchRunOut(**batches[0]),
        images=[GeneratedImageOut(**_coerce(img)) for img in images],
    )


@router.get("/{batch_id}/status", response_model=BatchRunOut, operation_id="getBatchStatus")
def get_batch_status(
    batch_id: str,
    ws: Dependencies.Client,
    db: Dependencies.DB,
):
    batches = _pg_fetch(db, "SELECT * FROM batch_runs WHERE batch_id = %s", (batch_id,))
    if not batches:
        raise HTTPException(404, "Batch not found")

    batch = batches[0]

    if batch["status"] == "running" and batch.get("job_run_id"):
        try:
            run = ws.jobs.get_run(run_id=int(batch["job_run_id"]))
            if run.state and run.state.life_cycle_state:
                life_cycle = run.state.life_cycle_state.value
                if life_cycle in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                    result_state = run.state.result_state.value if run.state.result_state else "UNKNOWN"
                    new_status = "completed" if result_state == "SUCCESS" else "failed"

                    counts = _pg_fetch(
                        db,
                        """SELECT count(*) AS total,
                               count(*) FILTER (WHERE status = 'success') AS successful
                           FROM generated_images WHERE batch_id = %s""",
                        (batch_id,),
                    )
                    total = counts[0]["total"] if counts else 0
                    successful = counts[0]["successful"] if counts else 0

                    _pg_execute(
                        db,
                        "UPDATE batch_runs SET status = %s, successful_images = %s, total_images = %s WHERE batch_id = %s",
                        (new_status, successful, total, batch_id),
                    )
                    batch["status"] = new_status
                    batch["successful_images"] = successful
                    batch["total_images"] = total
        except Exception:
            pass

    return BatchRunOut(**batch)


@router.delete("/{batch_id}", operation_id="deleteBatch")
def delete_batch(batch_id: str, db: Dependencies.DB):
    batches = _pg_fetch(db, "SELECT batch_id FROM batch_runs WHERE batch_id = %s", (batch_id,))
    if not batches:
        raise HTTPException(404, "Batch not found")
    _pg_execute(db, "DELETE FROM batch_runs WHERE batch_id = %s", (batch_id,))


@router.get(
    "/{batch_id}/images/{image_id}/versions",
    response_model=list[ImageVersionOut],
    operation_id="listImageVersions",
)
def list_image_versions(batch_id: str, image_id: int, db: Dependencies.DB):
    rows = _pg_fetch(
        db,
        "SELECT * FROM image_versions WHERE batch_id = %s AND image_id = %s ORDER BY version",
        (batch_id, image_id),
    )
    return [ImageVersionOut(**r) for r in rows]


@router.post(
    "/{batch_id}/images/{image_id}/regenerate",
    response_model=RegenerateResponse,
    operation_id="regenerateImage",
)
def regenerate_image(
    batch_id: str,
    image_id: int,
    body: RegenerateRequest,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    db: Dependencies.DB,
):
    images = _pg_fetch(
        db,
        "SELECT * FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    if not images:
        raise HTTPException(404, "Image not found")
    image = images[0]

    batches = _pg_fetch(db, "SELECT * FROM batch_runs WHERE batch_id = %s", (batch_id,))
    if not batches:
        raise HTTPException(404, "Batch not found")
    batch = batches[0]

    input_path = image["input_image_path"] if (body.use_source and image.get("input_image_path")) else image["volume_path"]
    if not input_path:
        raise HTTPException(400, "No image available for regeneration")

    try:
        resp = ws.files.download(input_path)
        input_b64 = base64.b64encode(resp.contents.read()).decode("utf-8")
    except Exception as e:
        raise HTTPException(500, f"Failed to read image: {e}")

    reference_b64 = None
    ref_path = batch.get("reference_image_path", "")
    if ref_path:
        try:
            resp = ws.files.download(ref_path)
            reference_b64 = base64.b64encode(resp.contents.read()).decode("utf-8")
        except Exception:
            pass

    size = batch.get("size") or "1024x1024"
    quality = batch.get("quality") or "low"
    image_model = batch.get("image_model") or "gpt-image-2"
    output_format = batch.get("output_format") or "png"
    background = batch.get("background") or "opaque"
    try:
        resp = ws.api_client.do(
            "POST",
            "/serving-endpoints/image-generator/invocations",
            body={
                "dataframe_split": {
                    "columns": [
                        "input_image_b64", "reference_image_b64", "prompt",
                        "size", "quality", "image_model", "output_format", "background",
                    ],
                    "data": [[
                        input_b64, reference_b64 or "", body.prompt,
                        size, quality, image_model, output_format, background,
                    ]],
                }
            },
        )
        prediction = resp["predictions"][0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Serving endpoint call failed: {e}")

    output_b64 = prediction.get("output_image_b64")
    status = prediction.get("status", "error")

    versions = _pg_fetch(
        db,
        "SELECT COALESCE(MAX(version), 0) AS max_v FROM image_versions WHERE batch_id = %s AND image_id = %s",
        (batch_id, image_id),
    )
    if versions[0]["max_v"] == 0:
        _pg_execute(
            db,
            """INSERT INTO image_versions
               (batch_id, image_id, version, prompt, status, error_message, volume_path)
               VALUES (%s, %s, 1, %s, %s, %s, %s)""",
            (batch_id, image_id, image["prompt"], image["status"], image.get("error_message"), image["volume_path"]),
        )
        versions[0]["max_v"] = 1

    next_version = versions[0]["max_v"] + 1

    new_volume_path = None
    if output_b64 and status == "success":
        img_bytes = base64.b64decode(output_b64)
        batch_output_path = f"{config.output_volume}/{batch_id}"
        filename = f"{image['image_name']}_generated_v{next_version}.jpeg"
        new_volume_path = f"{batch_output_path}/{filename}"
        try:
            ws.files.upload(new_volume_path, BytesIO(img_bytes), overwrite=True)
        except Exception as e:
            raise HTTPException(500, f"Failed to save regenerated image: {e}")

    _pg_execute(
        db,
        """INSERT INTO image_versions
           (batch_id, image_id, version, prompt, status, error_message, volume_path)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (batch_id, image_id, next_version, body.prompt, status, None, new_volume_path),
    )

    if new_volume_path and status == "success":
        _pg_execute(
            db,
            "UPDATE generated_images SET volume_path = %s, prompt = %s, status = %s WHERE batch_id = %s AND id = %s",
            (new_volume_path, body.prompt, status, batch_id, image_id),
        )

    updated_images = _pg_fetch(
        db,
        "SELECT * FROM generated_images WHERE batch_id = %s AND id = %s",
        (batch_id, image_id),
    )
    version_rows = _pg_fetch(
        db,
        "SELECT * FROM image_versions WHERE batch_id = %s AND image_id = %s AND version = %s",
        (batch_id, image_id, next_version),
    )

    return RegenerateResponse(
        image=GeneratedImageOut(**updated_images[0]),
        version=ImageVersionOut(**version_rows[0]),
    )
