#!/usr/bin/env python3
"""Seed base (母版) clauses for types that lack them, from the previously
LLM-generated contract templates in ``src/contracts/data/contracts.json``.

For each contract type with no ``base`` clauses in the DB, split its generated
``body`` into ``## <section>`` blocks and upsert each as a ``base`` clause
(``level=national``, ``source_path='generated:<key>'``). Idempotent via the
``(source_path, section, body_hash)`` unique index. ``slot_instructions`` and
``law_refs`` are re-derived from the body by ``upsert_clause``.

Usage::
    uv run python scripts/seed_generated_base.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.store import _finalize, upsert_clause  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402

_CONTRACTS = json.loads((Path(__file__).resolve().parents[1] / "src" / "contracts" / "data" / "contracts.json").read_text(encoding="utf-8"))
_SECTION_SPLIT = re.compile(r"^## ", re.M)


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split a generated body into (section, content) pairs by ``## `` headings."""
    out: list[tuple[str, str]] = []
    for chunk in _SECTION_SPLIT.split(body)[1:]:  # drop the pre-first-heading intro
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, rest = chunk.partition("\n")
        section = head.strip()
        content = rest.strip()
        if section and content:
            out.append((section, content))
    return out


def _types_without_base() -> set[str]:
    conn = connect(None)
    try:
        rows = conn.execute(
            "SELECT contract_type FROM clauses WHERE category='base' GROUP BY contract_type"
        ).fetchall()
    finally:
        conn.close()
    return {c["key"] for c in _CONTRACTS} - {r["contract_type"] for r in rows}


def main() -> int:
    ensure_schema()
    todo = _types_without_base()
    print(f"types without base: {len(todo)} -> seeding from generated templates", flush=True)
    total = 0
    for c in _CONTRACTS:
        key = c["key"]
        if key not in todo:
            continue
        zh = c["zh"]
        sections = _split_sections(c.get("body") or "")
        for section, content in sections:
            rec = _finalize(
                {
                    "contract_type": key,
                    "category": "base",
                    "section": section,
                    "body": content,
                    "province": None,
                    "level": "national",
                    "source_path": f"generated:{key}",
                    "source_doc_title": f"生成母版（{zh}）",
                    "slot_instructions": c.get("slot_instructions") or [],
                },
                content,
            )
            upsert_clause(rec)
            total += 1
        print(f"  {key} ({zh}): {len(sections)} sections", flush=True)
    print(f"\ninserted {total} base clauses across {len(todo)} types", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
