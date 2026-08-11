#!/usr/bin/env python3
"""Backfill ``pipeline_runs`` from output/self_iterate/*_report.json (V4/V5 runs).

Why this exists: the V4/V5 self-iteration batches (2026-08-10/11) ran via
scripts/self_iterate.py, which wrote only clauses + local JSON reports — never
``pipeline_runs``, the ONLY table the web dashboard reads
(src/web/routes/dashboard.py). So the dashboard showed nothing for V4/V5 even
though the clause effects were live. This synthesizes one ``pipeline_runs`` row
per contract type from its report (final round = the type's end state).

Idempotent: deletes prior rows tagged ``source='self_iterate_backfill'`` first.
``created_at`` is taken from each report file's mtime (≈ when the type's last
iteration ran) so dashboard chronology is faithful. Going forward,
scripts/self_iterate.py persists directly (see persist_pipeline_run there).

Usage:
    python scripts/backfill_pipeline_runs.py [--dry-run]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.eval.db import connect, close_shared_conn
from src.eval.pipeline_store import insert_pipeline_run
from src.eval.rubric import list_rubrics

BACKFILL_TAG = "self_iterate_backfill"


def latest_rubric(contract_type: str, rubric_names: list[str]) -> str:
    names = [n for n in rubric_names if n.startswith(f"contract_{contract_type}_")]
    return max(names) if names else f"contract_{contract_type}_v3"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reports = sorted(Path("output/self_iterate").glob("*_report.json"))
    if not reports:
        print("No reports found under output/self_iterate/")
        return 1

    # The sale pilot (2026-08-07, 3/10 → 10/10 over 4 rounds) predates report-saving,
    # so no sale_report.json exists. Synthesize it from docs/v4-final-results.md.
    entries: list[tuple[str, dict, str]] = []  # (ctype, report, created_at ISO)
    for path in reports:
        rep = json.loads(path.read_text(encoding="utf-8"))
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        rep["_task_desc"] = f"V4/V5 self-iteration (backfilled from {path})"
        entries.append((rep["type"], rep, mtime))
    if not any(c == "sale" for c, _, _ in entries):
        entries.append(("sale", {
            "type": "sale",
            "rounds": [{"round": 4, "score": 1.0, "n_passed": 10, "n_total": 10, "generated": []}],
            "all_pass": True,
            "final_round": 4,
            "_task_desc": "V4 sale pilot 3/10→10/10, 4 rounds (2026-08-07; predates report files — synthesized from docs/v4-final-results.md)",
        }, "2026-08-07T15:30:00+00:00"))

    rubric_names = [r["name"] for r in list_rubrics()]
    print(f"{len(reports)} report files (+synthetic sale = {len(entries)} rows)")

    conn = connect()
    try:
        deleted = conn.execute(
            "DELETE FROM pipeline_runs WHERE tags->>'source' = %s", (BACKFILL_TAG,)
        ).rowcount
        print(f"deleted {deleted} prior backfill rows")
    finally:
        close_shared_conn()

    inserted = 0
    for ctype, rep, created_at in entries:
        rounds = rep.get("rounds") or []
        last = rounds[-1] if rounds else {}
        actions = [g for r in rounds for g in r.get("generated", [])]
        row = {
            "contract_type": ctype,
            "tags": {"source": BACKFILL_TAG},
            "stance": "balanced",
            "rubric_name": latest_rubric(ctype, rubric_names),
            "task_desc": rep["_task_desc"],
            "score": last.get("score"),
            "max_score": last.get("n_total"),
            "n_passed": last.get("n_passed"),
            "n_criteria": last.get("n_total"),
            "all_pass": 1 if rep.get("all_pass") else 0,
            "iteration": rep.get("final_round", len(rounds) or 1),
            "actions_taken": actions,
        }
        if args.dry_run:
            print(f"[dry] {ctype}: {row['n_passed']}/{row['n_criteria']} "
                  f"all_pass={row['all_pass']} rounds={row['iteration']} at={created_at}")
            continue
        pid = insert_pipeline_run(row)
        conn = connect()
        try:
            conn.execute("UPDATE pipeline_runs SET created_at = %s WHERE id = %s", (created_at, pid))
        finally:
            close_shared_conn()
        inserted += 1
        print(f"  id={pid} {ctype}: {row['n_passed']}/{row['n_criteria']} "
              f"all_pass={row['all_pass']} rounds={row['iteration']}")

    print(f"\n{'[dry-run] would insert' if args.dry_run else 'inserted'} {len(entries)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
