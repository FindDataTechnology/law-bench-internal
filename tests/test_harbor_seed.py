"""Tests for ``src.eval.harbor_seed`` - bundled-seed self-heal of harbor rubrics.

These simulate the container: harbor is treated as not installed
(``find_harbor_package`` -> ``None``) so the heal loads from the bundled seed
pinned to ``harbor:v0.20.0``, making the tests hermetic and version-independent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.eval import harbor_seed
from src.eval import store


@pytest.fixture
def bundled_mode(monkeypatch) -> None:
    """Force the bundled-seed fallback (simulate harbor not installed)."""
    monkeypatch.setattr(harbor_seed, "find_harbor_package", lambda: None)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_ensure_heals_empty_db(tmp_path: Path, bundled_mode) -> None:
    db = tmp_path / "empty.db"
    assert not db.exists()

    summary = harbor_seed.ensure_harbor_rubrics(db)

    assert summary["rubrics"] == 2
    assert summary["criteria"] == 13
    assert summary["source_origin"] == "bundled"
    conn = _connect(db)
    try:
        rows = conn.execute(
            "SELECT name, source, context FROM rubrics WHERE source LIKE 'harbor:%' "
            "ORDER BY name"
        ).fetchall()
        assert [r[0] for r in rows] == ["task_quality", "trial_behavior"]
        assert all(r[1] == "harbor:v0.20.0" for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM criteria").fetchone()[0] == 13
    finally:
        conn.close()


def test_ensure_idempotent(tmp_path: Path, bundled_mode) -> None:
    db = tmp_path / "idem.db"
    harbor_seed.ensure_harbor_rubrics(db)
    harbor_seed.ensure_harbor_rubrics(db)

    conn = _connect(db)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM rubrics WHERE source LIKE 'harbor:%'"
        ).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM criteria").fetchone()[0] == 13
        # No duplicate criteria within a rubric (UNIQUE(rubric_id, name)).
        assert conn.execute(
            "SELECT COUNT(*) FROM criteria c1, criteria c2 "
            "WHERE c1.rubric_id = c2.rubric_id AND c1.name = c2.name AND c1.id < c2.id"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_ensure_preserves_local_and_eval(tmp_path: Path, bundled_mode) -> None:
    db = tmp_path / "stale.db"
    # Build a DB that looks like the stale volume: schema + a local rubric and
    # an eval_runs row, but no harbor rubrics.
    store.ensure_schema(db)  # eval_runs + compare_runs
    conn = _connect(db)
    try:
        harbor_seed.create_schema(conn)  # rubrics + criteria + prompts
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO rubrics (name, context, source, description, created_at) "
            "VALUES ('my_local', 'contract', 'local', 'a local rubric', ?)",
            (now,),
        )
        local_id = conn.execute(
            "SELECT id FROM rubrics WHERE name = 'my_local'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (?, 'c1', 'd', 'g', 0)",
            (local_id,),
        )
        conn.execute(
            "INSERT INTO eval_runs (rubric_name, contract_path, score, max_score, "
            "all_pass, n_criteria, n_passed, scored_at, created_at) "
            "VALUES ('my_local', 'c.md', 0.5, 1.0, 0, 1, 0, ?, ?)",
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()

    harbor_seed.ensure_harbor_rubrics(db)

    conn = _connect(db)
    try:
        # Local rubric + its criterion are untouched.
        local = conn.execute(
            "SELECT description FROM rubrics WHERE name = 'my_local' AND source = 'local'"
        ).fetchone()
        assert local is not None and local[0] == "a local rubric"
        assert conn.execute(
            "SELECT COUNT(*) FROM criteria WHERE rubric_id = ?", (local_id,)
        ).fetchone()[0] == 1
        # The eval_runs row is untouched.
        run = conn.execute(
            "SELECT rubric_name, score FROM eval_runs"
        ).fetchone()
        assert run[0] == "my_local" and run[1] == 0.5
        # Harbor rubrics were added alongside.
        assert conn.execute(
            "SELECT COUNT(*) FROM rubrics WHERE source LIKE 'harbor:%'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_load_uses_bundled_when_harbor_absent(monkeypatch) -> None:
    monkeypatch.setattr(harbor_seed, "find_harbor_package", lambda: None)

    loaded, origin = harbor_seed.load_harbor_rubrics()

    assert origin == "bundled"
    assert len(loaded) == 2
    names = sorted(r["name"] for r, _c, _s in loaded)
    assert names == ["task_quality", "trial_behavior"]
    assert all(s == "harbor:v0.20.0" for _r, _c, s in loaded)
    total_criteria = sum(len(c) for _r, c, _s in loaded)
    assert total_criteria == 13
