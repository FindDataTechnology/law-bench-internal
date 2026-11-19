#!/usr/bin/env python3
"""Import source candidates into the domain proposal inbox as crosswalk proposals.

A source candidate is a *proposal*, not an ontology fact: "this source fills this
part of the ontology" is a judgement someone must confirm. Writing it straight
into the ontology would make coverage look full while nobody had checked a thing.

Two things make this import honest:

- **来源是 `extract:`** — that prefix is accepted only in-process
  (`submitters.VIA_IN_PROCESS`). It says "this came from our extraction code",
  and the rule is enforced by the submitter gate, not by this script's goodwill.
- **只导入已声明对齐的候选** — a candidate with no `ontology_alignment` has
  nothing to assert about the ontology. Importing it would create a proposal
  whose evidence says "we supply this source" but not "it fills that concept",
  which is exactly the kind of claim nobody can review.

Idempotent: `proposals.submit` keys on `(domain, source, external_key)` and
returns the existing pending row unchanged, so re-running is safe and reports
idempotent hits separately from new rows.

Run (must be in the bench process — `extract:` is refused over HTTP):

    uv run python scripts/import_source_candidates.py --dry-run
    uv run python scripts/import_source_candidates.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CANDIDATES = (
    REPO_ROOT.parent / "data-source-scouting" / "candidates.json"
)

#: The submitter identity. `extract:<tool>:<version>` — the middle segment names
#: what produced these rows, so a reviewer can tell extraction output from a
#: fleet nomination at a glance.
SOURCE = "extract:source-scouting:1.0"

#: Crosswalk relation for "this source supplies observations for that concept
#: family". `maps_to` rather than `same_as`: a data source is not the *same* as
#: a concept, it fills one.
RELATION = "maps_to"


def adoption_plans(candidates: dict) -> list[dict]:
    """Proposals for candidates awaiting an adopt/don't-adopt decision.

    A `needs_review` candidate asks a different question from an aligned one:
    **"do we take this source?"**, not "which concept does it fill". Both are
    judgements only a person can make, so both belong in the inbox — but they
    must not be conflated. An adoption proposal carries no `mapping` and its
    confirmation writes no ontology unit; the decision itself is the record.

    Keyed `source:<id>` so one source's two questions (adopt it? what does it
    fill?) remain visibly about one source.
    """
    out = []
    for row in candidates.get("candidates", []):
        if not row.get("needs_review"):
            continue
        key = str(row.get("id") or row.get("name"))
        out.append({
            "name": row.get("name"),
            "external_key": f"source:{key}",
            "body": f"是否接入数据源「{row.get('name')}」（文档第 {row.get('doc_line')} 行）",
            "evidence": {
                "decision_pending": "needs_review",
                "source_status": row.get("status"),
                "doc_line": row.get("doc_line"),
                "section": row.get("section"),
                "vertical": row.get("vertical"),
                "endpoint": row.get("endpoint"),
            },
        })
    return out


def plans(candidates: dict, *, anchor: str) -> list[dict]:
    """One proposal per (candidate, concept family) it declares.

    The crosswalk断言 is "**our entity** `anchor` is filled by this source's
    observations for concept `C`". The local endpoint must therefore be a real
    entity of the domain — the inbox refuses to manufacture endpoints, which is
    the point: a mapping claims something already exists, it does not create it.

    `anchor` is that entity's key (e.g. a `region:guangdong` unit). The concept
    family goes in the evidence, not the key: it describes *what* the source
    supplies, while the key names *who* is supplied.
    """
    out = []
    for row in candidates.get("candidates", []):
        concepts = row.get("ontology_alignment") or []
        if not concepts:
            continue
        version = row.get("protocol_version")
        for concept in concepts:
            out.append({
                "name": row.get("name"),
                "concept": concept,
                "protocol_version": version,
                "external_key": f"{anchor}",
                "endpoint": row.get("endpoint"),
                "evidence": {
                    "mapping": {
                        "relation": RELATION,
                        "peer": {
                            "kind": "external_id",
                            "system": "source_catalog",
                            "id": str(row.get("id") or row.get("name")),
                        },
                        # Deliberately below the review floor (0.8): this is a
                        # machine declaration, and the platform only counts a
                        # mapping once a human confirms it. Writing a high
                        # confidence here would make AI declarations count as
                        # reviewed — the one thing the seam forbids.
                        "confidence": 0.5,
                    },
                    "concept_family": concept,
                    "source_name": row.get("name"),
                    "protocol_version": version,
                    "doc_line": row.get("doc_line"),
                },
            })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", default=str(CANDIDATES))
    ap.add_argument("--domain", default="erp",
                    help="target domain key (sources are business-ontology inputs)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--mode", choices=("alignment", "adoption"), default="alignment",
                    help="alignment=已声明对齐的候选写成 crosswalk 提案；"
                         "adoption=needs_review 的候选写成采纳提案")
    ap.add_argument("--anchor", default=None,
                    help="本域实体的键（如 organization:guangdong）；alignment 模式必填")
    args = ap.parse_args(argv)

    if args.mode == "alignment" and not args.anchor:
        print("alignment 模式必须给 --anchor：crosswalk 的本端是本域已存在的实体",
              file=sys.stderr)
        return 2

    path = Path(args.candidates)
    if not path.is_file():
        print(f"candidates file not found: {path}", file=sys.stderr)
        return 2
    candidates = json.loads(path.read_text(encoding="utf-8"))
    if args.mode == "adoption":
        rows = adoption_plans(candidates)
        kind = "source-adoption"
    else:
        rows = plans(candidates, anchor=args.anchor)
        kind = "crosswalk"
    if args.limit:
        rows = rows[: args.limit]

    total = len(candidates.get("candidates", []))
    involved = len({r["name"] for r in rows})
    if not rows:
        if args.mode == "adoption":
            print(f"{total} 条候选中没有 needs_review=true 的 —— 没有要导入的。")
        else:
            print(
                f"{total} 条候选，其中 0 条声明了本体对齐 —— 没有要导入的。\n"
                "这不是错误：对齐需要人逐条判断（change design D5）。"
            )
        return 0

    if args.mode == "adoption":
        print(f"{total} 条候选中 {involved} 条待决策（needs_review），共 {len(rows)} 条采纳提案")
    else:
        print(f"{total} 条候选中 {involved} 条声明了对齐，共 {len(rows)} 条断言")

    if args.dry_run:
        for r in rows:
            print(f"  would submit {r['external_key']:40s} ← {r['name']}")
        print("\nDRY-RUN — nothing written.")
        return 0

    import psycopg

    from src.bench import proposals, submitters
    from src.eval import db as edb
    from src.eval import store as eval_store

    conn = psycopg.connect(edb._dsn(), row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)
        created = idempotent = 0
        for r in rows:
            try:
                proposal, made = proposals.submit(
                    conn,
                    domain_key=args.domain,
                    source=SOURCE,
                    kind=kind,
                    external_key=r["external_key"],
                    body=r.get("body") or f"{r['name']} 提供 {r['concept']} 的观测数据",
                    evidence=r["evidence"],
                    submitted_by="system:source-scouting",
                    with_created=True,
                    via=submitters.VIA_IN_PROCESS,
                )
            except Exception as exc:  # noqa: BLE001 - report per row, keep going
                print(f"  SKIP {r['external_key']}: {exc}", file=sys.stderr)
                continue
            if made:
                created += 1
            else:
                idempotent += 1
        print(f"新增 {created} 条提案，幂等命中 {idempotent} 条")
        print(
            "这些是**待确认**提案：没有被确认之前不计入任何覆盖统计，"
            "也不会产生知识单元。"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())