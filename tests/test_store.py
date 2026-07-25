"""Unit tests for ``src/eval/store.py`` against a throwaway DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.eval.store import (
    ensure_schema,
    get_compare,
    get_run_draft,
    list_compares,
    list_runs,
    store_compare,
    store_result,
)


def _result(rubric: str = "r", all_pass: bool = False, n: int = 2, n_passed: int = 1) -> dict:
    return {
        "rubric": rubric,
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "all_pass": all_pass,
        "n_criteria": n,
        "n_passed": n_passed,
        "summary": "s",
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
        "criteria_results": [
            {"id": "c1", "title": "t1", "verdict": "pass", "reasoning": "ok"},
            {"id": "c2", "title": "t2", "verdict": "fail", "reasoning": "no"},
        ],
    }


def test_ensure_schema_idempotent(seeded_db: Path):
    ensure_schema(seeded_db)
    ensure_schema(seeded_db)  # second call must not error
    conn = sqlite3.connect(seeded_db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"eval_runs", "eval_criteria_results"} <= names


def test_store_result_round_trip(seeded_db: Path):
    rid = store_result(_result(), contract_path="out.md", task_desc="起草", db_path=seeded_db)
    assert isinstance(rid, int)
    runs = list_runs(db_path=seeded_db)
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == rid
    assert run["rubric_name"] == "r"
    assert run["score"] == 0.0
    assert run["all_pass"] == 0
    assert run["n_passed"] == 1
    assert run["n_criteria"] == 2
    assert run["contract_path"] == "out.md"


def test_list_runs_newest_first(seeded_db: Path):
    id1 = store_result(_result(rubric="r1"), db_path=seeded_db)
    id2 = store_result(_result(rubric="r2"), db_path=seeded_db)
    id3 = store_result(_result(rubric="r3"), db_path=seeded_db)
    runs = list_runs(db_path=seeded_db)
    assert [r["id"] for r in runs] == [id3, id2, id1]


def test_store_result_persists_criteria_verdicts(seeded_db: Path):
    rid = store_result(_result(), db_path=seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT criterion_id, verdict FROM eval_criteria_results WHERE run_id = ? ORDER BY ordinal",
        (rid,),
    ).fetchall()
    conn.close()
    assert [(r["criterion_id"], r["verdict"]) for r in rows] == [
        ("c1", "pass"),
        ("c2", "fail"),
    ]


# --- compare persistence + migration --------------------------------------- #


def _result_with_criteria(rubric="r", verdicts=(("c1", "pass"), ("c2", "fail"))) -> dict:
    return {
        "rubric": rubric,
        "score": 0.0,
        "max_score": 1.0,
        "all_pass": False,
        "n_criteria": len(verdicts),
        "n_passed": sum(1 for _, v in verdicts if v == "pass"),
        "summary": "s",
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
        "criteria_results": [
            {"id": cid, "title": f"t-{cid}", "verdict": v, "reasoning": "r"}
            for cid, v in verdicts
        ],
    }


def test_store_result_standalone_keeps_compare_cols_null(seeded_db: Path):
    """Standalone (non-compare) runs store with all compare columns null."""
    rid = store_result(_result_with_criteria(), db_path=seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT compare_run_id, prompt_name, prompt_type, variant_label, draft_text "
        "FROM eval_runs WHERE id = ?",
        (rid,),
    ).fetchone()
    conn.close()
    assert row["compare_run_id"] is None
    assert row["prompt_name"] is None
    assert row["draft_text"] is None


def test_store_compare_round_trip(seeded_db: Path):
    cid = store_compare("sale test", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    rid = store_result(
        _result_with_criteria(),
        task_desc="task",
        db_path=seeded_db,
        compare_run_id=cid,
        prompt_name="draft_sale",
        prompt_type="baseline",
        variant_label="baseline",
        draft_text="DRAFT",
    )
    assert isinstance(cid, int) and isinstance(rid, int)

    comps = list_compares(db_path=seeded_db)
    assert len(comps) == 1 and comps[0]["id"] == cid

    got = get_compare(cid, db_path=seeded_db)
    assert got["id"] == cid
    assert got["runs"][0]["prompt_name"] == "draft_sale"
    assert got["runs"][0]["prompt_type"] == "baseline"
    assert "draft_text" not in got["runs"][0]  # excluded from default payload

    d = get_run_draft(cid, rid, db_path=seeded_db)
    assert d["draft_text"] == "DRAFT"


def test_get_compare_survives_prompt_deletion(seeded_db: Path):
    """Snapshotted prompt metadata survives deletion of the prompt row (no FK)."""
    cid = store_compare("lbl", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    store_result(
        _result_with_criteria(),
        db_path=seeded_db,
        compare_run_id=cid,
        prompt_name="draft_sale",
        prompt_type="baseline",
        variant_label="baseline",
        draft_text="DRAFT",
    )
    # There is no prompts row in this fixture; the snapshot stands on its own.
    got = get_compare(cid, db_path=seeded_db)
    assert got["runs"][0]["prompt_name"] == "draft_sale"
    assert got["runs"][0]["prompt_type"] == "baseline"


def test_get_run_draft_rejects_wrong_compare(seeded_db: Path):
    cid = store_compare("lbl", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    rid = store_result(
        _result_with_criteria(), db_path=seeded_db, compare_run_id=cid, prompt_name="p",
    )
    import pytest

    with pytest.raises(KeyError):
        get_run_draft(cid + 999, rid, db_path=seeded_db)  # run belongs to a different compare


def test_migration_adds_columns_to_old_eval_runs(tmp_path: Path):
    """An eval_runs table created pre-change (no compare cols) is migrated in place."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    # Old shape: eval_runs without the compare-driven columns.
    conn.execute(
        "CREATE TABLE eval_runs (id INTEGER PRIMARY KEY, rubric_name TEXT, score REAL)"
    )
    conn.execute("INSERT INTO eval_runs (rubric_name, score) VALUES ('r', 0.0)")
    conn.commit()
    conn.close()

    ensure_schema(db)  # should ALTER the existing table
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_runs)")}
    conn.close()
    assert {"compare_run_id", "prompt_name", "prompt_type", "variant_label", "draft_text"} <= cols
    # existing row's new columns are null
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT compare_run_id, draft_text FROM eval_runs WHERE id = 1").fetchone()
    conn.close()
    assert row["compare_run_id"] is None and row["draft_text"] is None

    ensure_schema(db)  # idempotent: no error on second run
    assert {"compare_run_id", "draft_text"} <= cols


def test_migration_creates_compare_runs_table(seeded_db: Path):
    ensure_schema(seeded_db)
    conn = sqlite3.connect(seeded_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "compare_runs" in tables
