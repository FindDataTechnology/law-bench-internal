"""Low-level PostgreSQL helpers shared by the eval manage and store layers.

Centralizes connection setup (dict-row factory, single source of truth = the
``database_url`` env var), the UTC timestamp helper, the harbor-provenance
predicate, and criterion renumbering, so the CRUD modules and the run-store do
not each redefine them.

Connection model: ``connect(db)`` is a passthrough-or-open factory. If ``db``
is already a live ``psycopg`` connection (e.g. injected by a test fixture or a
request dependency), it is returned unchanged; otherwise a new connection is
opened from the ``database_url`` environment variable. The historical
``db_path`` parameter name is retained across the CRUD/store surface for
call-site compatibility, but it now carries an *optional connection* - a
filesystem path is no longer used (PostgreSQL is addressed by DSN).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

from src.settings import ConfigError


class _BorrowedConn:
    """Wrap a connection so ``close()`` is a no-op.

    CRUD/store functions open a connection, use it, and ``close()`` it in a
    ``finally``. When a *request* (via ``get_db``) or a *test* injects a shared
    connection, that borrower must not close it - the owner (the request scope
    or the test fixture) manages its lifetime. This proxy delegates
    ``execute``/``commit`` (and anything else via ``__getattr__``) to the real
    connection while making ``close()`` a no-op, so the existing
    ``try/finally: conn.close()`` pattern is safe for both owned and borrowed
    connections.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self, *args, **kwargs):
        return self._conn.commit(*args, **kwargs)

    def close(self) -> None:  # borrower does not own the connection
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def is_connection(obj) -> bool:
    """True if ``obj`` looks like a live DB connection (duck-typed)."""
    return obj is not None and hasattr(obj, "execute") and hasattr(obj, "commit")


def _dsn() -> str:
    """The PostgreSQL DSN from env (``database_url`` or ``DATABASE_URL``)."""
    load_dotenv()
    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise ConfigError(
            "database_url is not set (expected a PostgreSQL DSN, e.g. "
            "postgresql://user:pass@host:5432/db)."
        )
    return dsn


def connect(db: Any = None) -> Any:
    """Return a psycopg connection (or a borrowed-connection wrapper).

    If ``db`` is already a live connection (e.g. injected by a request
    dependency or a test fixture), return a ``_BorrowedConn`` wrapping it so the
    caller's ``finally: conn.close()`` does not close the shared connection.
    Otherwise open a new connection from ``database_url`` with a dict-row
    factory. Any non-connection ``db`` value (e.g. a legacy ``Path`` default) is
    ignored and a fresh connection is opened from the DSN.
    """
    import psycopg  # local import keeps module import light
    from psycopg.rows import dict_row

    if is_connection(db):
        return _BorrowedConn(db)
    conn = psycopg.connect(_dsn(), row_factory=dict_row)
    # Foreign keys are enforced by default in PostgreSQL (no PRAGMA needed).
    return conn


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def is_harbor(source: Optional[str]) -> bool:
    """True if the rubric source marks it as a read-only harbor reference."""
    return bool(source) and source.startswith("harbor:")


def column_exists(conn, table: str, col: str) -> bool:
    """True if ``table`` has a column named ``col`` (PostgreSQL information_schema)."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, col),
    ).fetchone()
    return row is not None


def table_exists(conn, table: str) -> bool:
    """True if ``table`` exists in the public schema."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None


def renumber_criteria(conn, rubric_id: int) -> None:
    """Reassign ordinal to be contiguous 0..N-1 in current order."""
    rows = conn.execute(
        "SELECT id FROM criteria WHERE rubric_id = %s ORDER BY ordinal, id",
        (rubric_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE criteria SET ordinal = %s WHERE id = %s",
            (i, r["id"]),
        )
