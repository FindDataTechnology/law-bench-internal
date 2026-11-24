"""Ruler tools: the standards a domain evaluates against.

A "ruler" is a rubric plus its criteria — the thing that turns a draft into a
score. Rubrics are domain-scoped by reference (`src.bench.domain_rubrics`): a
child domain sees its ancestors' rubrics and may fork one with a recorded diff.
Both tools here are read-only and domain-scoped; `domain` is required for the
same reason as in `domain.py` — resolution without a domain can read across
domains.
"""

from __future__ import annotations

from typing import Optional

from ..annotations import annotations_for
from ..server import mcp


def _resolve(conn, domain: str) -> dict:
    from src.bench import workspaces

    if not domain:
        raise ValueError(
            "domain is required: the assistant works inside one domain at a time"
        )
    row = workspaces.get_domain(conn, domain_key=domain)
    if row is None:
        raise ValueError(f"unknown domain {domain!r}")
    return row


@mcp.tool(tags={"rulers"}, annotations=annotations_for("ruler_list"))
async def ruler_list(domain: str) -> list[dict]:
    """Every rubric visible to this domain, nearest definition winning.

    A rubric defined on an ancestor is inherited by reference; a rubric the
    domain forked keeps its own row and its `fork_diff` explains how it differs.
    Two rubrics with the same name in different ancestors are one standard with
    an override — only the nearest is returned.

    Parameters:
        domain: the domain key.
    """
    from src.eval.db import connect
    from src.bench import domain_rubrics

    conn = connect()
    try:
        row = _resolve(conn, domain)
        standards = domain_rubrics.effective_rubrics(
            conn, domain_path=row.get("path") or row["key"]
        )
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "context": r.get("context"),
                "source": r.get("source"),
                "domain_id": r.get("domain_id"),
                "derived_from": r.get("derived_from"),
                "fork_diff": r.get("fork_diff"),
            }
            for r in standards
        ]
    finally:
        conn.close()


@mcp.tool(tags={"rulers"}, annotations=annotations_for("ruler_criteria"))
async def ruler_criteria(domain: str, rubric: Optional[str] = None,
                         rubric_id: Optional[int] = None) -> dict:
    """One ruler's criteria, in order.

    Parameters:
        domain: the domain key — the rubric must be visible to this domain.
        rubric: the rubric's name (as returned by `ruler_list`).
        rubric_id: alternatively, its id.

    Exactly one of `rubric` / `rubric_id` must be given.
    """
    from src.eval.db import connect
    from src.bench import domain_rubrics

    if not rubric and rubric_id is None:
        raise ValueError("give either rubric (name) or rubric_id")
    conn = connect()
    try:
        row = _resolve(conn, domain)
        standards = domain_rubrics.effective_rubrics(
            conn, domain_path=row.get("path") or row["key"]
        )
        match = None
        for s in standards:
            if rubric_id is not None and s.get("id") == rubric_id:
                match = s
                break
            if rubric and s.get("name") == rubric:
                match = s
                break
        if match is None:
            which = repr(rubric) if rubric else rubric_id
            raise ValueError(
                f"rubric {which} is not visible to domain {domain!r}"
            )
        full = domain_rubrics.get_by_id(conn, rubric_id=match["id"])
        return {
            "id": full.get("id"),
            "name": full.get("name"),
            "context": full.get("context"),
            "criteria": full.get("criteria") or [],
        }
    finally:
        conn.close()