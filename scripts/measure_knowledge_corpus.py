#!/usr/bin/env python3
"""Phase 0 measurement for `<audit-knowledge-units-clause-corpus>` task 1.1/1.4.

Deterministic, zero-LLM scan of every ``kind='clause'`` unit in ``knowledge_units``:
region_lint hits (split attribution vs. content), ``{{slot}}`` placeholder counts,
exact-body dedup groups per namespace, namespace/tier distribution, empty/short/long
body census, and PDF-extraction line-break artifacts. Writes a machine-readable JSON
plus a human-readable summary into the change's ``notes/`` directory — that report IS
this change's scope lock (design D2).

Corpus shape note (measured 2026-11-26): the live rows are *statute articles*
(``<law_key>#第N条``), adopted from the Qdrant ``law-library``. So:

- soft-deleted rows (``tags.deleted=true``) are tombstones — excluded from the
  live corpus stats; counted separately so a reader can see them.
- SAR/region references (``台湾地区``/``香港特别行政区``/``澳门特别行政区``) inside a
  national statute are *legitimate legal scoping*, not the "local regulation
  hardcoded into a template" defect the predecessor change targeted.
- PDF-extraction breakage (``\\n，`` mid-sentence) is the one deterministic,
  repairable defect class the live corpus actually carries.

Usage::

    uv run python scripts/measure_knowledge_corpus.py            # writes both files
    uv run python scripts/measure_knowledge_corpus.py --print    # also echo summary

Only reads. No LLM, no writes to ``knowledge_units``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

# override=True: the shell often exports empty LLM/DATABASE vars; load_dotenv's
# default override=False would treat them as already set (same reason every
# sibling driver in scripts/ does this).
load_dotenv(override=True)

from src.clauses.audit import region_lint  # noqa: E402
from src.eval.db import connect  # noqa: E402

CHANGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fd-coding-law-bench-mcp/openspec/changes/audit-knowledge-units-clause-corpus"
)

#: Source-page footer signatures ("网站标识码 bm…", "京公网安备…") that
#: region_lint can trip on because they contain a place name. These are not
#: clause content — the region-audit rewrites must not touch them.
_ATTRIBUTION_RE = re.compile(
    r"公网安备|网站标识码|政府网站识别码|网站访问量|主办单位|承办单位|"
    r"国务院\s*互联网\+督查|移动客户端|政府网站找错|ICP备|版权所有"
)
#: SAR / region references that appear *by necessity* in national law
#: (cross-strait / cross-border scope rules). A statute naming 台湾地区 is not
#: local-law leakage — it is the rule's own subject. Not a content defect.
_LEGIT_REGION_RE = re.compile(r"香港特别行政区|澳门特别行政区|台湾地区")
#: PDF extraction breakage: a newline (optionally with an ideographic space)
#: immediately before closing punctuation, or right after opening punctuation.
_BREAK_BEFORE_PUNCT = re.compile(r"\n[\s　]*[，。、；：）】」』！？]")
_BREAK_AFTER_OPEN = re.compile(r"[（【「『]\s*[\n　]+")

_SHORT_BODY_CHARS = 10
_LONG_BODY_CHARS = 2000


def _normalize(body: str) -> str:
    """Whitespace-insensitive body identity for dedup grouping."""
    return re.sub(r"\s+", "", body or "")


def _body_hash(body: str) -> str:
    return hashlib.sha256(_normalize(body).encode("utf-8")).hexdigest()


def _is_deleted(row: dict) -> bool:
    return bool((row.get("tags") or {}).get("deleted"))


def _classify_region_hits(body: str) -> str:
    """'attribution' | 'legit_region' | 'content' | 'unknown' for a lint-hit body.

    - attribution: a scraped page footer (publisher signature line).
    - legit_region: the hit is a SAR/region reference a national statute names
      by necessity (cross-strait / cross-border scope).
    - content: anything else — a genuine locality reference to review.
    """
    body = body or ""
    if _ATTRIBUTION_RE.search(body):
        return "attribution"
    if _LEGIT_REGION_RE.search(body):
        return "legit_region"
    return "content"


def _extraction_artifact(body: str) -> bool:
    return bool(_BREAK_BEFORE_PUNCT.search(body) or _BREAK_AFTER_OPEN.search(body))


def measure() -> dict:
    conn = connect()
    try:
        rows = [
            dict(r) for r in conn.execute(
                "SELECT id, namespace, external_key, body, tier, tags "
                "FROM knowledge_units WHERE kind = 'clause' ORDER BY id"
            ).fetchall()
        ]
    finally:
        conn.close()

    live = [r for r in rows if not _is_deleted(r)]
    deleted = len(rows) - len(live)

    namespace_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    region_hits: list[dict] = []
    region_classes: Counter[str] = Counter()
    slot_rows: list[dict] = []
    empty_bodies: list[int] = []
    short_bodies: list[int] = []
    long_bodies: list[int] = []
    artifact_ids: list[int] = []
    artifact_samples: list[dict] = []
    hash_groups: dict[str, list[dict]] = {}

    slot_re = re.compile(r"\{\{\s*\w+\s*\}\}")
    for r in live:
        namespace_counts[r["namespace"]] += 1
        tier_counts[r["tier"]] += 1
        body = r["body"] or ""

        hits = region_lint(body)
        if hits:
            cls = _classify_region_hits(body)
            region_classes[cls] += 1
            region_hits.append({
                "id": r["id"],
                "external_key": r["external_key"],
                "matches": hits,
                "class": cls,
                "tail": body[-60:],
            })

        slots = slot_re.findall(body)
        if slots:
            slot_rows.append({"id": r["id"], "slots": slots})

        stripped = body.strip()
        if not stripped:
            empty_bodies.append(r["id"])
        elif len(stripped) < _SHORT_BODY_CHARS:
            short_bodies.append(r["id"])
        if len(stripped) > _LONG_BODY_CHARS:
            long_bodies.append(r["id"])

        if _extraction_artifact(body):
            artifact_ids.append(r["id"])
            if len(artifact_samples) < 5:
                artifact_samples.append(
                    {"id": r["id"], "external_key": r["external_key"], "head": body[:100]}
                )

        hash_groups.setdefault(_body_hash(body), []).append({
            "id": r["id"],
            "namespace": r["namespace"],
            "external_key": r["external_key"],
        })

    dup_groups = [
        {"body_hash": h, "members": members}
        for h, members in hash_groups.items() if len(members) > 1
    ]
    dup_member_rows = sum(len(g["members"]) for g in dup_groups)

    # Deleted twins: soft-deleted legacy-prefix copies whose live counterpart
    # shares the body. Reported separately — they are NOT a live-corpus defect.
    all_groups: dict[str, list[dict]] = {}
    for r in rows:
        all_groups.setdefault(_body_hash(r["body"]), []).append(r)
    deleted_twin_groups = sum(
        1 for members in all_groups.values()
        if any(_is_deleted(m) for m in members) and any(not _is_deleted(m) for m in members)
    )

    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "table": "knowledge_units",
        "kind": "clause",
        "totals": {
            "rows": len(rows),
            "live": len(live),
            "soft_deleted": deleted,
            "unique_live_body_hashes": len(hash_groups),
            "live_dup_groups": len(dup_groups),
            "live_dup_member_rows": dup_member_rows,
            "deleted_twin_groups": deleted_twin_groups,
        },
        "namespace_distribution": dict(namespace_counts),
        "tier_distribution": dict(tier_counts),
        "region_lint": {
            "live_rows_with_hits": len(region_hits),
            "class_counts": dict(region_classes),
            "rows": region_hits,
        },
        "slots": {
            "live_rows_with_slots": len(slot_rows),
            "rows": slot_rows,
        },
        "body_census": {
            "empty": empty_bodies,
            "short_lt_%d" % _SHORT_BODY_CHARS: short_bodies,
            "long_gt_%d" % _LONG_BODY_CHARS: long_bodies,
        },
        "extraction_artifacts": {
            "live_rows": len(artifact_ids),
            "samples": artifact_samples,
        },
        "dedup": {
            "live_groups": dup_groups,
        },
    }


def _scope_switches(report: dict) -> dict:
    rl = report["region_lint"]["class_counts"]
    t = report["totals"]
    return {
        "region_content_leaks": rl.get("content", 0),
        "region_legit_or_attribution": rl.get("legit_region", 0) + rl.get("attribution", 0),
        "slot_bodies": report["slots"]["live_rows_with_slots"],
        "dup_redundant_rows": t["live_dup_member_rows"],
        "extraction_artifact_bodies": report["extraction_artifacts"]["live_rows"],
        "empty_bodies": len(report["body_census"]["empty"]),
        "too_short_bodies": len(report["body_census"]["short_lt_10"]),
    }


def summary_text(report: dict) -> str:
    t = report["totals"]
    rl = report["region_lint"]
    sw = _scope_switches(report)
    return "\n".join([
        f"# Phase 0 measurement — knowledge_units kind='clause'",
        f"measured_at: {report['measured_at']}",
        f"rows: {t['rows']}  live: {t['live']}  soft_deleted: {t['soft_deleted']}",
        f"namespaces: {report['namespace_distribution']}  tiers: {report['tier_distribution']}",
        "",
        "## Scope switches (live corpus)",
        f"region content leaks (real defects): {sw['region_content_leaks']}",
        f"region legit/attribution (not defects): {sw['region_legit_or_attribution']}",
        f"slot bodies: {sw['slot_bodies']}",
        f"duplicate redundant rows: {sw['dup_redundant_rows']}  "
        f"(deleted-twin groups, not a defect: {t['deleted_twin_groups']})",
        f"extraction-artifact bodies (PDF line-break breakage): {sw['extraction_artifact_bodies']}",
        f"empty bodies: {sw['empty_bodies']}  too short (<{_SHORT_BODY_CHARS}): {sw['too_short_bodies']}",
        "",
        "## Region-lint detail (live)",
        f"rows with hits: {rl['live_rows_with_hits']}  classes: {rl['class_counts']}",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="echo the summary to stdout")
    args = ap.parse_args()

    report = measure()
    notes = CHANGE_DIR / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    json_path = notes / "phase0-measurement.json"
    txt_path = notes / "phase0-summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = summary_text(report)
    txt_path.write_text(summary + "\n", encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {txt_path}")
    if args.do_print:
        print()
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
