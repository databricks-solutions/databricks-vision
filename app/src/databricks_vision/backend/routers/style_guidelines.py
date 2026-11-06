"""CRUD for named style guidelines / brand kits (analyzer criteria + logo, palette, typography)."""
from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from PIL import Image as PILImage
from PIL import UnidentifiedImageError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..models import (
    StyleGuidelineCreate,
    StyleGuidelineOut,
    StyleGuidelineUpdate,
)

router = APIRouter(tags=["style-guidelines"])

_COLUMNS = "id, name, body, is_default, logo_path, palette, typography, created_at, updated_at"
_HEX_COLOUR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_MAX_PALETTE = 8
_MAX_LOGO_BYTES = 10 * 1024 * 1024
_LOGO_FORMATS = {"PNG": (".png", "image/png"), "JPEG": (".jpg", "image/jpeg"), "WEBP": (".webp", "image/webp")}


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


def _row_to_out(row: dict) -> StyleGuidelineOut:
    palette = row.get("palette") or []
    if isinstance(palette, str):
        palette = json.loads(palette)
    return StyleGuidelineOut(
        id=row["id"],
        name=row["name"],
        body=row.get("body") or "",
        is_default=bool(row.get("is_default")),
        logo_path=row.get("logo_path") or "",
        palette=palette,
        typography=row.get("typography") or "",
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _clean_palette(palette: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(c.strip().upper() for c in palette if c.strip()))
    bad = [c for c in cleaned if not _HEX_COLOUR_RE.match(c)]
    if bad:
        raise HTTPException(400, f"Palette colours must be hex like #1A73E8; got {', '.join(bad)}")
    if len(cleaned) > _MAX_PALETTE:
        raise HTTPException(400, f"At most {_MAX_PALETTE} palette colours")
    return cleaned


def _clear_default_if_set(pool: ConnectionPool, except_id: int | None = None) -> None:
    if except_id is None:
        _pg_execute(pool, "UPDATE style_guidelines SET is_default = FALSE WHERE is_default")
    else:
        _pg_execute(
            pool,
            "UPDATE style_guidelines SET is_default = FALSE WHERE is_default AND id <> %s",
            (except_id,),
        )


def _pool(request: Request) -> ConnectionPool:
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    return pool


def get_brand_kit(pool: ConnectionPool, guideline_id: int) -> StyleGuidelineOut:
    """Fetch one style guideline / brand kit or raise 404 (also used by Compose)."""
    rows = _pg_fetch(pool, f"SELECT {_COLUMNS} FROM style_guidelines WHERE id = %s", (guideline_id,))
    if not rows:
        raise HTTPException(404, "Style guideline not found")
    return _row_to_out(rows[0])


@router.get(
    "/style-guidelines",
    response_model=list[StyleGuidelineOut],
    operation_id="listStyleGuidelines",
)
def list_style_guidelines(request: Request):
    rows = _pg_fetch(
        _pool(request),
        f"SELECT {_COLUMNS} FROM style_guidelines ORDER BY is_default DESC, name ASC",
    )
    return [_row_to_out(r) for r in rows]


@router.post(
    "/style-guidelines",
    response_model=StyleGuidelineOut,
    operation_id="createStyleGuideline",
)
def create_style_guideline(body: StyleGuidelineCreate, request: Request):
    pool = _pool(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    palette = _clean_palette(body.palette)

    if body.is_default:
        _clear_default_if_set(pool)

    rows = _pg_fetch(
        pool,
        f"""INSERT INTO style_guidelines (name, body, is_default, palette, typography)
           VALUES (%s, %s, %s, %s::jsonb, %s)
           RETURNING {_COLUMNS}""",
        (name, body.body, body.is_default, json.dumps(palette), body.typography),
    )
    if not rows:
        raise HTTPException(500, "Failed to create style guideline")
    return _row_to_out(rows[0])


@router.patch(
    "/style-guidelines/{guideline_id}",
    response_model=StyleGuidelineOut,
    operation_id="updateStyleGuideline",
)
def update_style_guideline(guideline_id: int, body: StyleGuidelineUpdate, request: Request):
    pool = _pool(request)
    get_brand_kit(pool, guideline_id)  # 404 if missing

    if body.is_default is True:
        _clear_default_if_set(pool, except_id=guideline_id)

    sets: list[str] = []
    params: list[Any] = []
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "name cannot be empty")
        sets.append("name = %s")
        params.append(name)
    if body.body is not None:
        sets.append("body = %s")
        params.append(body.body)
    if body.is_default is not None:
        sets.append("is_default = %s")
        params.append(body.is_default)
    if body.palette is not None:
        sets.append("palette = %s::jsonb")
        params.append(json.dumps(_clean_palette(body.palette)))
    if body.typography is not None:
        sets.append("typography = %s")
        params.append(body.typography)
    if not sets:
        # No-op update — just return the row.
        return get_brand_kit(pool, guideline_id)

    sets.append("updated_at = NOW()")
    params.append(guideline_id)
    rows = _pg_fetch(
        pool,
        f"""UPDATE style_guidelines SET {", ".join(sets)}
            WHERE id = %s
            RETURNING {_COLUMNS}""",
        tuple(params),
    )
    if not rows:
        raise HTTPException(404, "Style guideline not found")
    return _row_to_out(rows[0])


@router.delete(
    "/style-guidelines/{guideline_id}",
    operation_id="deleteStyleGuideline",
)
def delete_style_guideline(guideline_id: int, request: Request):
    rows = _pg_fetch(
        _pool(request),
        "DELETE FROM style_guidelines WHERE id = %s RETURNING id",
        (guideline_id,),
    )
    if not rows:
        raise HTTPException(404, "Style guideline not found")
    return {"deleted": True, "id": guideline_id}


# --- Brand-kit logo ---------------------------------------------------------------------


@router.post(
    "/style-guidelines/{guideline_id}/logo",
    response_model=StyleGuidelineOut,
    operation_id="uploadStyleGuidelineLogo",
)
async def upload_logo(guideline_id: int, logo: UploadFile, request: Request):
    """Store a raster logo (PNG / JPEG / WebP) for a brand kit. The original bytes are kept,
    so transparency survives; Compose attaches the logo as a reference image."""
    pool = _pool(request)
    get_brand_kit(pool, guideline_id)
    data = await logo.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(400, "Logo must be 10 MB or smaller")
    try:
        fmt = PILImage.open(BytesIO(data)).format
    except UnidentifiedImageError:
        raise HTTPException(400, "Logo must be a PNG, JPEG or WebP image")
    if fmt not in _LOGO_FORMATS:
        raise HTTPException(400, f"Logo must be a PNG, JPEG or WebP image; got {fmt}")

    cfg = request.app.state.config
    path = f"{cfg.vision_volume}/brand-kits/{guideline_id}/logo{_LOGO_FORMATS[fmt][0]}"
    request.app.state.workspace_client.files.upload(path, BytesIO(data), overwrite=True)
    rows = _pg_fetch(
        pool,
        f"""UPDATE style_guidelines SET logo_path = %s, updated_at = NOW()
            WHERE id = %s RETURNING {_COLUMNS}""",
        (path, guideline_id),
    )
    return _row_to_out(rows[0])


def read_logo(request: Request, logo_path: str) -> bytes:
    """Download a brand-kit logo from its Volume path."""
    try:
        return request.app.state.workspace_client.files.download(logo_path).contents.read()
    except Exception as exc:
        raise HTTPException(404, f"Could not read logo: {exc}")


@router.get("/style-guidelines/{guideline_id}/logo", operation_id="getStyleGuidelineLogo")
def get_logo(guideline_id: int, request: Request):
    kit = get_brand_kit(_pool(request), guideline_id)
    if not kit.logo_path:
        raise HTTPException(404, "This brand kit has no logo")
    media_type = next(
        (mime for ext, mime in _LOGO_FORMATS.values() if kit.logo_path.endswith(ext)), "image/png"
    )
    return Response(content=read_logo(request, kit.logo_path), media_type=media_type)


@router.delete(
    "/style-guidelines/{guideline_id}/logo",
    response_model=StyleGuidelineOut,
    operation_id="deleteStyleGuidelineLogo",
)
def delete_logo(guideline_id: int, request: Request):
    """Detach the logo (the Volume file is left in place, like other deletes in this app)."""
    pool = _pool(request)
    get_brand_kit(pool, guideline_id)
    rows = _pg_fetch(
        pool,
        f"""UPDATE style_guidelines SET logo_path = '', updated_at = NOW()
            WHERE id = %s RETURNING {_COLUMNS}""",
        (guideline_id,),
    )
    return _row_to_out(rows[0])
