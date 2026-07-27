"""FastAPI dependencies for the evaluation-rules web app.

``get_db`` is the seam that lets tests point the web layer at a throwaway
database via ``app.dependency_overrides[get_db] = ...`` instead of mutating the
development database. It returns a PostgreSQL connection resolved from the
``database_url`` environment variable (no longer a filesystem ``Path``); CRUD
functions borrow it without closing it (see ``src/eval/db._BorrowedConn``).
"""

from __future__ import annotations

from typing import Any


def get_db() -> Any:
    """Return a PostgreSQL connection for the web layer to read/write.

    Opens a connection from ``database_url``. Tests override this through
    ``app.dependency_overrides[get_db]`` to inject a connection to a throwaway
    test database.
    """
    from src.eval.db import connect  # local import avoids a circular import at load

    return connect()
