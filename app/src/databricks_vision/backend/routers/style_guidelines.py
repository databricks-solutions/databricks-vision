"""CRUD for named style guidelines (analyzer criteria templates)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..models import (
    StyleGuidelineCreate,
    StyleGuidelineOut,
    StyleGuidelineUpdate,
)

router = APIRouter(tags=["style-guidelines"])


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
    return StyleGuidelineOut(
        id=row["id"],
        name=row["name"],
        body=row.get("body") or "",
        is_default=bool(row.get("is_default")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _clear_default_if_set(pool: ConnectionPool, except_id: int | None = None) -> None:
    if except_id is None:
        _pg_execute(pool, "UPDATE style_guidelines SET is_default = FALSE WHERE is_default")
    else:
        _pg_execute(
            pool,
            "UPDATE style_guidelines SET is_default = FALSE WHERE is_default AND id <> %s",
            (except_id,),
        )


@router.get(
    "/style-guidelines",
    response_model=list[StyleGuidelineOut],
    operation_id="listStyleGuidelines",
)
def list_style_guidelines(request: Request):
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    rows = _pg_fetch(
        pool,
        "SELECT id, name, body, is_default, created_at, updated_at FROM style_guidelines ORDER BY is_default DESC, name ASC",
    )
    return [_row_to_out(r) for r in rows]


@router.post(
    "/style-guidelines",
    response_model=StyleGuidelineOut,
    operation_id="createStyleGuideline",
)
def create_style_guideline(body: StyleGuidelineCreate, request: Request):
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")

    if body.is_default:
        _clear_default_if_set(pool)

    rows = _pg_fetch(
        pool,
        """INSERT INTO style_guidelines (name, body, is_default)
           VALUES (%s, %s, %s)
           RETURNING id, name, body, is_default, created_at, updated_at""",
        (name, body.body, body.is_default),
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
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")

    existing = _pg_fetch(
        pool, "SELECT id FROM style_guidelines WHERE id = %s", (guideline_id,)
    )
    if not existing:
        raise HTTPException(404, "Style guideline not found")

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
    if not sets:
        # No-op update — just return the row.
        rows = _pg_fetch(
            pool,
            "SELECT id, name, body, is_default, created_at, updated_at FROM style_guidelines WHERE id = %s",
            (guideline_id,),
        )
        return _row_to_out(rows[0])

    sets.append("updated_at = NOW()")
    params.append(guideline_id)
    rows = _pg_fetch(
        pool,
        f"""UPDATE style_guidelines SET {", ".join(sets)}
            WHERE id = %s
            RETURNING id, name, body, is_default, created_at, updated_at""",
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
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    rows = _pg_fetch(
        pool,
        "DELETE FROM style_guidelines WHERE id = %s RETURNING id",
        (guideline_id,),
    )
    if not rows:
        raise HTTPException(404, "Style guideline not found")
    return {"deleted": True, "id": guideline_id}
