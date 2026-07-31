"""Tag review helpers: per-dim approve/reject + assembly-ready check.

A clause is "assembly-ready" when every dim in its ``tags`` has
``tag_review[dim] == "approved"``. Assembly uses only assembly-ready custom
clauses; base/tagged are the backbone (not gated).

Review supports two granularities (per the design):
- per-dim: :func:`review_tag` sets one dim's status.
- bulk: :func:`bulk_review` sets all of a clause's tag dims to one status.
"""

from __future__ import annotations

from typing import Any

from src.eval.db import connect
from src.eval.errors import NotFoundError
from src.eval.store import ensure_schema

_REVIEW_STATUSES = ("pending", "approved", "rejected")


def is_assembly_ready(clause: dict) -> bool:
    """True when every set tag dim has ``tag_review[dim] == 'approved'``."""
    tags = clause.get("tags") or {}
    review = clause.get("tag_review") or {}
    return all(review.get(dim) == "approved" for dim in tags)


def review_tag(clause_id: int, dim: str, status: str, db: Any = None) -> None:
    """Set ``tag_review[dim] = status`` for one clause (per-dim review)."""
    if status not in _REVIEW_STATUSES:
        raise ValueError(f"invalid status: {status!r}; use one of {_REVIEW_STATUSES}")
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "UPDATE clauses SET tag_review = tag_review || jsonb_build_object(%s::text, %s::text) WHERE id = %s",
            (dim, status, clause_id),
        )
        conn.commit()
        if (cur.rowcount or 0) == 0:
            raise NotFoundError(f"clause not found: {clause_id}")
    finally:
        if db is None:
            conn.close()


def bulk_review(clause_id: int, status: str, db: Any = None) -> None:
    """Set ALL of a clause's tag dims to ``status`` (bulk approve/reject)."""
    if status not in _REVIEW_STATUSES:
        raise ValueError(f"invalid status: {status!r}; use one of {_REVIEW_STATUSES}")
    from psycopg.types.json import Jsonb

    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute("SELECT tags FROM clauses WHERE id = %s", (clause_id,)).fetchone()
        if r is None:
            raise NotFoundError(f"clause not found: {clause_id}")
        new_review = {k: status for k in (r["tags"] or {})}
        conn.execute(
            "UPDATE clauses SET tag_review = %s WHERE id = %s",
            (Jsonb(new_review), clause_id),
        )
        conn.commit()
    finally:
        if db is None:
            conn.close()


def list_pending(clause_type: str | None = None, db: Any = None) -> list[dict]:
    """Return clauses that have at least one pending tag dim (for the review UI)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        sql = (
            "SELECT * FROM clauses WHERE "
            "EXISTS (SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'pending')"
        )
        params: list = []
        if clause_type:
            sql += " AND contract_type = %s"
            params.append(clause_type)
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
    finally:
        if db is None:
            conn.close()
    from src.clauses.store import _row_to_dict

    return [_row_to_dict(r) for r in rows]
