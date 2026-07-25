"""Low-level SQLite helpers shared by the eval manage and store layers.

Centralizes connection setup (row factory + foreign keys), the UTC timestamp
helper, the harbor-provenance predicate, and criterion renumbering, so the CRUD
modules and the run-store do not each redefine them.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.settings import DEFAULT_DB


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open a connection returning Row rows, with foreign keys enforced."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # so ON DELETE CASCADE fires
    return conn


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def is_harbor(source: Optional[str]) -> bool:
    """True if the rubric source marks it as a read-only harbor reference."""
    return bool(source) and source.startswith("harbor:")


def renumber_criteria(conn: sqlite3.Connection, rubric_id: int) -> None:
    """Reassign ordinal to be contiguous 0..N-1 in current order."""
    rows = conn.execute(
        "SELECT id FROM criteria WHERE rubric_id = ? ORDER BY ordinal, id",
        (rubric_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute("UPDATE criteria SET ordinal = ? WHERE id = ?", (i, r["id"]))
