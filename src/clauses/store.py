"""Postgres CRUD for the ``clauses`` table (base / tagged / custom).

Reuses :func:`src.eval.db.connect` (the shared connection model - a request or
test can inject a borrowed connection) and :func:`src.eval.store.ensure_schema`
(so the table exists on first write). Idempotent upsert for base/tagged clauses
is keyed on ``(source_path, section, body_hash)`` via a partial unique index;
custom clauses (``source_path`` null) are plain inserts by id.

Dashboard-created/edited clauses carry ``manual=true`` so re-extraction
(:func:`delete_auto_clauses`) preserves them.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from psycopg.types.json import Jsonb

from src.eval.db import connect
from src.eval.errors import NotFoundError
from src.eval.store import ensure_schema

from .extract import _law_refs_from_body, _normalize_slot_instructions, section_rank

_INSERT_COLS = (
    "contract_type, category, section, body, slot_instructions, law_refs, "
    "province, level, source_path, source_doc_title, body_hash, created_at, updated_at, manual"
)


def _now() -> str:
    from src.eval.db import now_iso

    return now_iso()


def _row(clause: dict, *, now: str) -> tuple:
    # Enforce category semantics defensively (the extractor already sets these):
    # custom -> no source_path; base -> national + no province; tagged -> local.
    category = clause["category"]
    source_path = clause.get("source_path")
    province = clause.get("province")
    level = clause.get("level")
    if category == "custom":
        source_path = None
        level = None
    elif category == "base":
        province = None
        level = "national"
    elif category == "tagged":
        level = "local"
    return (
        clause["contract_type"],
        category,
        clause["section"],
        clause["body"],
        Jsonb(clause.get("slot_instructions") or []),
        Jsonb(clause.get("law_refs") or []),
        province,
        level,
        source_path,
        clause.get("source_doc_title"),
        clause["body_hash"],
        now,
        now,
        bool(clause.get("manual", False)),
    )


def _finalize(clause: dict, body: str) -> dict:
    """Re-derive ``body_hash``/``slot_instructions``/``law_refs`` from ``body``.

    ``slot_instructions`` keeps existing labels/descriptions for surviving slots
    and stubs any new ``{{slot}}``; ``law_refs`` is the ``《...》`` provisions.
    """
    body = (body or "").strip()
    return {
        **clause,
        "body": body,
        "body_hash": hashlib.md5(body.encode("utf-8")).hexdigest(),
        "slot_instructions": _normalize_slot_instructions(body, clause.get("slot_instructions") or []),
        "law_refs": _law_refs_from_body(body),
    }


def upsert_clause(clause: dict, db: Any = None) -> int:
    """Insert (or update on conflict) one clause; return its id.

    ``manual`` is taken from ``clause`` (false for auto-extracted). On conflict
    ``manual`` is left unchanged so a re-extract never un-marks a curated clause.
    """
    ensure_schema(db)
    now = _now()
    conn = connect(db)
    try:
        values = _row(clause, now=now)
        if clause.get("source_path") is not None:
            cur = conn.execute(
                "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (source_path, section, body_hash) WHERE source_path IS NOT NULL "
                "DO UPDATE SET contract_type=EXCLUDED.contract_type, category=EXCLUDED.category, "
                "section=EXCLUDED.section, body=EXCLUDED.body, "
                "slot_instructions=EXCLUDED.slot_instructions, law_refs=EXCLUDED.law_refs, "
                "province=EXCLUDED.province, level=EXCLUDED.level, "
                "source_doc_title=EXCLUDED.source_doc_title, body_hash=EXCLUDED.body_hash, "
                "updated_at=EXCLUDED.updated_at RETURNING id",
                values,
            )
        else:
            cur = conn.execute(
                "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                values,
            )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def upsert_clauses(clauses: list[dict], db: Any = None) -> int:
    """Upsert many clauses in one connection; return the number written."""
    ensure_schema(db)
    if not clauses:
        return 0
    now = _now()
    conn = connect(db)
    try:
        for clause in clauses:
            values = _row(clause, now=now)
            if clause.get("source_path") is not None:
                conn.execute(
                    "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (source_path, section, body_hash) WHERE source_path IS NOT NULL "
                    "DO UPDATE SET contract_type=EXCLUDED.contract_type, category=EXCLUDED.category, "
                    "section=EXCLUDED.section, body=EXCLUDED.body, "
                    "slot_instructions=EXCLUDED.slot_instructions, law_refs=EXCLUDED.law_refs, "
                    "province=EXCLUDED.province, level=EXCLUDED.level, "
                    "source_doc_title=EXCLUDED.source_doc_title, body_hash=EXCLUDED.body_hash, "
                    "updated_at=EXCLUDED.updated_at",
                    values,
                )
            else:
                conn.execute(
                    "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    values,
                )
        conn.commit()
        return len(clauses)
    finally:
        conn.close()


def create_clause(clause: dict, db: Any = None) -> int:
    """Create a dashboard clause (``manual=true``, no corpus source).

    ``slot_instructions``/``law_refs``/``body_hash`` are re-derived from
    ``body``. Category semantics are enforced via :func:`_row`; ``source_path``
    is forced to null (dashboard clauses have no corpus origin).
    """
    ensure_schema(db)
    rec = _finalize({**clause, "source_path": None, "manual": True}, clause.get("body", ""))
    now = _now()
    conn = connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            _row(rec, now=now),
        )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def update_clause(clause_id: int, fields: dict, db: Any = None) -> dict:
    """Update a clause by id; re-derive body-dependent fields; set ``manual=true``.

    ``fields`` may carry ``body``, ``section``, ``category``, ``province``.
    Unspecified fields keep their existing value. Raises :class:`NotFoundError`
    for an unknown id. ``slot_instructions``/``law_refs``/``body_hash`` are
    re-derived from the (possibly edited) body.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
        if r is None:
            raise NotFoundError(f"clause not found: {clause_id}")
        existing = _row_to_dict(r)
        body = (fields.get("body") if fields.get("body") is not None else existing["body"]).strip()
        category = fields.get("category") or existing["category"]
        section = fields.get("section") or existing["section"]
        province = fields.get("province") if "province" in fields else existing["province"]
        slot_instructions = _normalize_slot_instructions(body, existing.get("slot_instructions") or [])
        law_refs = _law_refs_from_body(body)
        body_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
        # enforce category semantics
        source_path = existing["source_path"]
        level = existing["level"]
        if category == "custom":
            source_path = None
            level = None
        elif category == "base":
            province = None
            level = "national"
        elif category == "tagged":
            level = "local"
        now = _now()
        conn.execute(
            "UPDATE clauses SET section=%s, body=%s, slot_instructions=%s, law_refs=%s, "
            "body_hash=%s, category=%s, province=%s, level=%s, source_path=%s, manual=true, updated_at=%s "
            "WHERE id=%s",
            (section, body, Jsonb(slot_instructions), Jsonb(law_refs), body_hash, category,
             province, level, source_path, now, clause_id),
        )
        conn.commit()
        r2 = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
        return _row_to_dict(r2)
    finally:
        conn.close()


def delete_clause(clause_id: int, db: Any = None) -> int:
    """Delete one clause by id; return the count (1). Raise :class:`NotFoundError` if missing."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute("DELETE FROM clauses WHERE id = %s", (clause_id,))
        conn.commit()
        if (cur.rowcount or 0) == 0:
            raise NotFoundError(f"clause not found: {clause_id}")
        return cur.rowcount
    finally:
        conn.close()


def delete_clauses(source_path: str, db: Any = None) -> int:
    """Delete every clause sourced from ``source_path``; return the count."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "DELETE FROM clauses WHERE source_path = %s", (source_path,)
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def delete_auto_clauses(source_path: str, db: Any = None) -> int:
    """Delete auto-extracted clauses for ``source_path`` (``manual IS NOT TRUE``).

    Used by re-extraction so dashboard-curated (``manual=true``) clauses for the
    source survive a refresh.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "DELETE FROM clauses WHERE source_path = %s AND (manual IS NOT TRUE)",
            (source_path,),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "contract_type": r["contract_type"],
        "category": r["category"],
        "section": r["section"],
        "body": r["body"],
        "slot_instructions": r["slot_instructions"] or [],
        "law_refs": r["law_refs"] or [],
        "province": r["province"],
        "level": r["level"],
        "source_path": r["source_path"],
        "source_doc_title": r["source_doc_title"],
        "body_hash": r["body_hash"],
        "manual": r["manual"] if "manual" in r.keys() else False,
    }


def list_clauses(
    contract_type: Optional[str] = None,
    *,
    category: Optional[str] = None,
    province: Optional[str] = None,
    q: Optional[str] = None,
    db: Any = None,
) -> list[dict]:
    """Return clauses filtered by type/category/province/body-text, in section order.

    ``contract_type`` null returns all types. ``q`` does a case-insensitive
    ``ILIKE`` over ``body`` and ``source_doc_title``. Ordered by ``section_rank``
    then id.
    """
    ensure_schema(db)
    where = []
    params: list = []
    if contract_type is not None:
        where.append("contract_type = %s")
        params.append(contract_type)
    if category is not None:
        where.append("category = %s")
        params.append(category)
    if province is not None:
        where.append("province = %s")
        params.append(province)
    if q:
        where.append("(body ILIKE %s OR source_doc_title ILIKE %s)")
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    sql = "SELECT * FROM clauses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    conn = connect(db)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    out = [_row_to_dict(r) for r in rows]
    out.sort(key=lambda c: (section_rank(c["section"]), c["id"]))
    return out


def search_clauses(
    q: Optional[str] = None,
    *,
    contract_type: Optional[str] = None,
    category: Optional[str] = None,
    province: Optional[str] = None,
    db: Any = None,
) -> list[dict]:
    """Free-text search across clause bodies/titles, composed with the filters."""
    return list_clauses(contract_type, category=category, province=province, q=q, db=db)


def get_custom_clause(clause_id: int, db: Any = None) -> Optional[dict]:
    """Return one clause by id (used for custom clauses); None if missing."""
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(r) if r else None


def list_extracted_source_paths(db: Any = None) -> list[str]:
    """Distinct ``source_path`` values already extracted (for resumable runs)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_path FROM clauses WHERE source_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [r["source_path"] for r in rows]


def count_clauses(db: Any = None) -> dict:
    """Return ``{total, base, tagged, custom}`` counts (for the web overview)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM clauses GROUP BY category"
        ).fetchall()
    finally:
        conn.close()
    by_cat = {r["category"]: r["n"] for r in rows}
    return {
        "total": sum(by_cat.values()),
        "base": by_cat.get("base", 0),
        "tagged": by_cat.get("tagged", 0),
        "custom": by_cat.get("custom", 0),
    }


def counts_by_type(db: Any = None) -> list[dict]:
    """Per ``contract_type`` counts broken down by category + distinct provinces.

    Returns ``[{contract_type, base, tagged, custom, provinces:[...]}]`` ordered
    by contract_type. Used by the ``/clauses`` browse page.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT contract_type, category, province, COUNT(*) AS n "
            "FROM clauses GROUP BY contract_type, category, province "
            "ORDER BY contract_type"
        ).fetchall()
    finally:
        conn.close()
    by_type: dict[str, dict] = {}
    for r in rows:
        entry = by_type.setdefault(
            r["contract_type"], {"contract_type": r["contract_type"], "base": 0, "tagged": 0, "custom": 0, "provinces": set()}
        )
        entry[r["category"]] = entry.get(r["category"], 0) + r["n"]
        if r["category"] == "tagged" and r["province"]:
            entry["provinces"].add(r["province"])
    return [
        {**e, "provinces": sorted(e["provinces"])} for e in by_type.values()
    ]
