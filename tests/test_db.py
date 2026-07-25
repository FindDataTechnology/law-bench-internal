"""Unit tests for the shared helpers in ``src/eval/db.py``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.eval.db import connect, is_harbor, renumber_criteria


def test_connect_sets_row_factory_and_foreign_keys(seeded_db: Path):
    conn = connect(seeded_db)
    try:
        assert conn.row_factory is sqlite3.Row
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk[0] == 1
    finally:
        conn.close()


def test_is_harbor_predicate():
    assert is_harbor("harbor:v0.20.0") is True
    assert is_harbor("local") is False
    assert is_harbor(None) is False
    assert is_harbor("") is False


def test_renumber_criteria_contiguous(seeded_db: Path):
    conn = connect(seeded_db)
    try:
        rid = conn.execute(
            "SELECT id FROM rubrics WHERE name = 'l_rubric'"
        ).fetchone()["id"]
        # punch gaps in the ordinals, then renumber
        conn.execute("UPDATE criteria SET ordinal = 5 WHERE rubric_id = ?", (rid,))
        conn.commit()
        renumber_criteria(conn, rid)
        ordinals = [
            r["ordinal"]
            for r in conn.execute(
                "SELECT ordinal FROM criteria WHERE rubric_id = ? ORDER BY ordinal",
                (rid,),
            ).fetchall()
        ]
        conn.commit()
    finally:
        conn.close()
    assert ordinals == [0, 1]
