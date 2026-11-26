#!/usr/bin/env python3
"""Deterministic PDF-linebreak repair for ``knowledge_units`` clause bodies.

Phase 0 (``scripts/measure_knowledge_corpus.py``) measured 1210 live ``kind='clause'``
bodies carrying PDF extraction breakage — a hard newline inside a sentence
(``…活动\\n，``). That is the ONE defect class this change's Phase 0 found firing on
real data (region content leaks / slot / duplicate all measured 0). It is repaired
deterministically (no LLM) by :func:`src.bench.corpus_catalog.normalize_pdf_linebreaks`,
the same normaliser wired into the ingestion path so future adoptions carry no
breakage either.

Lineage safety (spec "Lineage-safe, reversible writes"): a rewrite touches ONLY
``body`` and ``updated_at``. ``provenance``/``derived_from``/``attrs``/``tags``/
``tier``/``external_key`` are never in the UPDATE statement, so the upsert identity
and bloodline cannot drift. The original body is written to
``output/audit-ku/<id>.json`` BEFORE the DB write, so every unit is revertible.

Usage::

    python scripts/repair_clause_linebreaks.py --dry-run   # count + sample, write nothing
    python scripts/repair_clause_linebreaks.py             # write originals, then UPDATE
    python scripts/repair_clause_linebreaks.py --revert    # restore every saved original

No LLM. Idempotent: a body already normalised (no-op) is skipped and not recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.bench.corpus_catalog import normalize_pdf_linebreaks  # noqa: E402
from src.eval.db import connect  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "audit-ku"
OPERATOR = "repair-linebreaks"


def _load_targets(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, external_key, body FROM knowledge_units "
        "WHERE kind = 'clause' AND COALESCE(tags->>'deleted', 'false') <> 'true' "
        "ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        body = (r["body"] if isinstance(r, dict) else r[2]) or ""
        fixed = normalize_pdf_linebreaks(body)
        if fixed != body:
            ident = r["id"] if isinstance(r, dict) else r[0]
            key = r["external_key"] if isinstance(r, dict) else r[1]
            out.append({"id": ident, "external_key": key, "original": body, "fixed": fixed})
    return out


def _revert(conn) -> int:
    files = sorted(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    if not files:
        print(f"no originals under {OUTPUT_DIR}; nothing to revert")
        return 0
    n = 0
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        conn.execute(
            "UPDATE knowledge_units SET body = %s, updated_at = now() WHERE id = %s",
            (rec["original"], rec["id"]),
        )
        n += 1
    conn.commit()
    print(f"reverted {n} unit(s) from {OUTPUT_DIR}")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count + sample, write nothing")
    ap.add_argument("--revert", action="store_true", help="restore saved originals")
    ap.add_argument("--limit", type=int, default=0, help="cap units processed (0 = all)")
    args = ap.parse_args(argv)

    conn = connect()
    try:
        if args.revert:
            _revert(conn)
            return 0

        targets = _load_targets(conn)
        print(f"live clause bodies needing repair: {len(targets)}")
        if targets and args.limit:
            targets = targets[: args.limit]
            print(f"capped to {len(targets)}")

        if args.dry_run:
            for t in targets[:5]:
                print(f"  #{t['id']} {t['external_key']}")
                print("   before:", repr(t["original"][:70]))
                print("   after :", repr(t["fixed"][:70]))
            print("[dry-run] nothing written")
            return 0

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        for t in targets:
            rec = {
                "id": t["id"],
                "external_key": t["external_key"],
                "operator": OPERATOR,
                "original": t["original"],
                "fixed": t["fixed"],
            }
            (OUTPUT_DIR / f"{t['id']}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # Only body + updated_at change; bloodline columns are untouched.
            conn.execute(
                "UPDATE knowledge_units SET body = %s, updated_at = now() WHERE id = %s",
                (t["fixed"], t["id"]),
            )
            written += 1
        conn.commit()
        print(f"repaired {written} unit(s); originals in {OUTPUT_DIR}")
        print(f"revert with: python scripts/repair_clause_linebreaks.py --revert")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
