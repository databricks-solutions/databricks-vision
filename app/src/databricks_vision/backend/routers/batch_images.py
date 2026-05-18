from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from psycopg.rows import dict_row

from ..core import Dependencies

router = APIRouter(prefix="/batch-images", tags=["batch-images"])


def _read_volume_file(ws, path: str) -> bytes:
    resp = ws.files.download(path)
    return resp.contents.read()


def _media_type(path: str) -> str:
    p = path.lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def _candidate_image_names(filename: str) -> list[str]:
    """Map an FE URL slug to candidate `image_name` values to match in DB.

    The FE appends `_generated.<ext>` to image_name when it doesn't have a real
    volume_path basename — strip that suffix so the lookup hits the actual row.
    Falls through to the literal slug for cases that don't follow that pattern.
    """
    candidates = {filename}
    for suffix in ("_generated.jpeg", "_generated.jpg", "_generated.png", "_generated.webp"):
        if filename.endswith(suffix):
            candidates.add(filename[: -len(suffix)])
    return list(candidates)


@router.get("/{batch_id}/{filename}", operation_id="getGeneratedImage")
def get_generated_image(
    batch_id: str,
    filename: str,
    ws: Dependencies.UserClient,
    db: Dependencies.DB,
):
    """Resolve the actual volume_path from the DB instead of trusting `output_volume` —
    rows can point at any volume (notebook outputs, ingested images, batch-job runs).
    """
    candidates = _candidate_image_names(filename)
    like_patterns = [f"%/{c}" for c in candidates]
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT volume_path FROM generated_images
                WHERE batch_id = %s
                  AND (image_name = ANY(%s) OR volume_path LIKE ANY(%s))
                ORDER BY id LIMIT 1
                """,
                (batch_id, candidates, like_patterns),
            )
            row = cur.fetchone()

    if not row or not row.get("volume_path"):
        raise HTTPException(404, f"No DB row for {batch_id}/{filename}")
    path = row["volume_path"]
    try:
        content = _read_volume_file(ws, path)
    except Exception as e:
        raise HTTPException(404, f"Image not found or access denied: {e}")
    return Response(content=content, media_type=_media_type(path))


@router.get("/source", operation_id="getSourceImage")
def get_source_image(
    path: str,
    ws: Dependencies.UserClient,
):
    if not path.startswith("/Volumes/"):
        raise HTTPException(400, "Path must start with /Volumes/")
    try:
        content = _read_volume_file(ws, path)
    except Exception as e:
        raise HTTPException(404, f"Image not found or access denied: {e}")
    return Response(content=content, media_type=_media_type(path))
