#!/usr/bin/env python3
"""Migrate data from the legacy SQLite DB (``db/evaluation_rules.db``) to PostgreSQL.

Strategy (per design Decision 9):

- **Rubrics / criteria / prompts** are re-seeded against PostgreSQL via the
  idempotent seeders (``harbor_seed`` + ``seed_contract_rubrics`` +
  ``seed_contract_prompts``), which upsert by natural key (``name``). This is
  the canonical source and avoids ID remapping between the two databases.
- **eval_runs / eval_criteria_results** (runtime data not produced by seeders)
  are copied row-by-row from SQLite, remapping ``run_id``. ``compare_runs`` are
  copied if present (none in the legacy DB at migration time).

The SQLite file is left in place (not deleted) as a backup until the PostgreSQL
path is verified end-to-end.

Run:
    uv run python scripts/migrate_sqlite_to_postgres.py
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.eval.harbor_seed import ensure_harbor_rubrics  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.settings import DEFAULT_DB  # noqa: E402

SQLITE_DB = REPO_ROOT / "db" / "evaluation_rules.db"

_EVAL_RUNS_COLS = (
    "rubric_name", "contract_path", "task_desc", "score", "max_score", "all_pass",
    "n_criteria", "n_passed", "summary", "judge_model", "scored_at", "created_at",
    "compare_run_id", "prompt_name", "prompt_type", "variant_label", "draft_text",
)
_EVAL_CRIT_COLS = ("criterion_id", "title", "verdict", "reasoning", "ordinal")


def _replay_seeders() -> None:
    """Re-run the harbor + contract seeders against PostgreSQL (idempotent)."""
    print("Ensuring harbor rubrics + schema on PostgreSQL...")
    summary = ensure_harbor_rubrics(DEFAULT_DB)
    print(f"  harbor: {summary['rubrics']} rubrics / {summary['criteria']} criteria "
          f"({summary['source_origin']})")
    ensure_schema(DEFAULT_DB)

    for script in ("seed_contract_rubrics.py", "seed_contract_prompts.py"):
        print(f"Running scripts/{script} against PostgreSQL...")
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  {script} failed (exit {proc.returncode}):\n{proc.stderr.strip()}",
                  file=sys.stderr)
            raise SystemExit(proc.returncode)
        if proc.stdout.strip():
            print(f"  {proc.stdout.strip().splitlines()[-1]}")


def _copy_runtime_data() -> None:
    """Copy eval_runs + eval_criteria_results from SQLite (id remapping)."""
    if not SQLITE_DB.is_file():
        print(f"No SQLite DB at {SQLITE_DB}; skipping runtime-data copy.")
        return

    sconn = sqlite3.connect(SQLITE_DB)
    sconn.row_factory = sqlite3.Row
    n_runs = sconn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0]
    n_compares = sconn.execute("SELECT COUNT(*) FROM compare_runs").fetchone()[0]
    print(f"SQLite runtime data: {n_runs} eval_runs, {n_compares} compare_runs")
    if n_runs == 0 and n_compares == 0:
        sconn.close()
        return

    pg = connect(DEFAULT_DB)
    try:
        # compare_runs first (eval_runs.compare_run_id references them).
        compare_id_map: dict[int, int | None] = {}
        for r in sconn.execute(
            "SELECT id, label, contract_type, rubric_name, task_desc, gen_mode, "
            "n_drafts, created_at FROM compare_runs"
        ):
            cur = pg.execute(
                "INSERT INTO compare_runs (label, contract_type, rubric_name, task_desc, "
                "gen_mode, n_drafts, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (r["label"], r["contract_type"], r["rubric_name"], r["task_desc"],
                 r["gen_mode"], r["n_drafts"], r["created_at"]),
            )
            compare_id_map[r["id"]] = cur.fetchone()["id"]

        run_id_map: dict[int, int] = {}
        placeholders = ",".join("%s" for _ in _EVAL_RUNS_COLS)
        for r in sconn.execute(f"SELECT id, {','.join(_EVAL_RUNS_COLS)} FROM eval_runs"):
            vals = [r[c] for c in _EVAL_RUNS_COLS]
            # remap compare_run_id (None stays None)
            old_cid = vals[_EVAL_RUNS_COLS.index("compare_run_id")]
            if old_cid is not None:
                vals[_EVAL_RUNS_COLS.index("compare_run_id")] = compare_id_map.get(old_cid)
            cur = pg.execute(
                f"INSERT INTO eval_runs ({','.join(_EVAL_RUNS_COLS)}) "
                f"VALUES ({placeholders}) RETURNING id",
                vals,
            )
            run_id_map[r["id"]] = cur.fetchone()["id"]

        cph = ",".join("%s" for _ in _EVAL_CRIT_COLS)
        for r in sconn.execute(f"SELECT run_id, {','.join(_EVAL_CRIT_COLS)} FROM eval_criteria_results"):
            pg.execute(
                f"INSERT INTO eval_criteria_results (run_id, {','.join(_EVAL_CRIT_COLS)}) "
                f"VALUES (%s, {cph})",
                (run_id_map[r["run_id"]], *[r[c] for c in _EVAL_CRIT_COLS]),
            )
        pg.commit()
        print(f"  copied {len(run_id_map)} eval_runs, "
              f"{len(compare_id_map)} compare_runs (ids remapped).")
    finally:
        pg.close()
        sconn.close()


def _verify() -> None:
    """Print row counts in PostgreSQL after migration."""
    pg = connect(DEFAULT_DB)
    try:
        for t in ("rubrics", "criteria", "prompts", "eval_runs",
                  "eval_criteria_results", "compare_runs"):
            n = pg.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            print(f"  pg.{t}: {n}")
    finally:
        pg.close()


def main() -> int:
    print("Migrating SQLite -> PostgreSQL (database_url).")
    _replay_seeders()
    _copy_runtime_data()
    print("PostgreSQL row counts after migration:")
    _verify()
    print(f"\nSQLite file left in place at {SQLITE_DB} (backup).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
