"""CRUD for the fixed set of 5 image-evaluation criteria (the metric grid).

Four built-ins (quality/prompt/text/safe) have editable instructions; `custom` is fully
user-defined (label + instructions) and disabled by default until enabled. No create/delete —
the set is fixed. Editing a criterion refreshes the live ImageEvaluator so changes take effect
without an app restart. Seed + schema live in image_gen._SCHEMA_SQL; defaults for
reset-to-default come from _eval.DEFAULT_CRITERIA.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..core._eval import DEFAULT_CRITERIA
from ..models import EvalCriterionOut, EvalCriterionUpdate

router = APIRouter(tags=["eval-criteria"])

_DEFAULTS_BY_KEY = {c["key"]: c for c in DEFAULT_CRITERIA}


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


def _row_to_out(row: dict) -> EvalCriterionOut:
    return EvalCriterionOut(
        key=row["key"],
        label=row["label"],
        instructions=row.get("instructions") or "",
        is_custom=bool(row.get("is_custom")),
        enabled=bool(row.get("enabled")),
    )


def _refresh_evaluator(request: Request) -> None:
    """Rebuild the live evaluator's judges from the updated criteria (no restart needed)."""
    evaluator = getattr(request.app.state, "image_evaluator", None)
    pool = getattr(request.app.state, "db_pool", None)
    if evaluator is not None:
        try:
            evaluator.refresh_criteria(pool)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("evaluator refresh_criteria failed", exc_info=True)


@router.get("/eval-criteria", response_model=list[EvalCriterionOut], operation_id="listEvalCriteria")
def list_eval_criteria(request: Request):
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    rows = _pg_fetch(
        pool,
        "SELECT key, label, instructions, is_custom, enabled FROM eval_criteria "
        "ORDER BY sort_order, key",
    )
    return [_row_to_out(r) for r in rows]


@router.patch(
    "/eval-criteria/{key}",
    response_model=EvalCriterionOut,
    operation_id="updateEvalCriterion",
)
def update_eval_criterion(key: str, body: EvalCriterionUpdate, request: Request):
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")

    existing = _pg_fetch(
        pool,
        "SELECT key, label, instructions, is_custom, enabled FROM eval_criteria WHERE key = %s",
        (key,),
    )
    if not existing:
        raise HTTPException(404, f"Unknown criterion {key!r}")
    row = existing[0]
    is_custom = bool(row["is_custom"])

    sets: list[str] = []
    params: list[Any] = []
    if body.instructions is not None:
        if not body.instructions.strip():
            raise HTTPException(400, "instructions cannot be empty")
        sets.append("instructions = %s")
        params.append(body.instructions)
    if body.label is not None:
        # Only the custom criterion may be relabeled; built-in labels are fixed.
        if not is_custom:
            raise HTTPException(400, "Only the custom criterion's label can be changed")
        if not body.label.strip():
            raise HTTPException(400, "label cannot be empty")
        sets.append("label = %s")
        params.append(body.label.strip())
    if body.enabled is not None:
        sets.append("enabled = %s")
        params.append(body.enabled)

    if sets:
        sets.append("updated_at = NOW()")
        params.append(key)
        _pg_execute(pool, f"UPDATE eval_criteria SET {', '.join(sets)} WHERE key = %s", tuple(params))
        _refresh_evaluator(request)

    updated = _pg_fetch(
        pool,
        "SELECT key, label, instructions, is_custom, enabled FROM eval_criteria WHERE key = %s",
        (key,),
    )
    return _row_to_out(updated[0])


@router.post(
    "/eval-criteria/{key}/reset",
    response_model=EvalCriterionOut,
    operation_id="resetEvalCriterion",
)
def reset_eval_criterion(key: str, request: Request):
    """Restore a built-in criterion's default instructions (and label) from DEFAULT_CRITERIA."""
    pool: ConnectionPool = request.app.state.db_pool
    if not pool:
        raise HTTPException(500, "Database not available")
    default = _DEFAULTS_BY_KEY.get(key)
    if not default:
        raise HTTPException(404, f"Unknown criterion {key!r}")
    _pg_execute(
        pool,
        "UPDATE eval_criteria SET label = %s, instructions = %s, updated_at = NOW() WHERE key = %s",
        (default["label"], default["instructions"], key),
    )
    _refresh_evaluator(request)
    updated = _pg_fetch(
        pool,
        "SELECT key, label, instructions, is_custom, enabled FROM eval_criteria WHERE key = %s",
        (key,),
    )
    if not updated:
        raise HTTPException(404, f"Unknown criterion {key!r}")
    return _row_to_out(updated[0])
