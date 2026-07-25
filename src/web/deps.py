"""FastAPI dependencies for the evaluation-rules web app.

``get_db`` is the seam that lets tests point the web layer at a throwaway
database via ``app.dependency_overrides[get_db] = ...`` instead of mutating the
development database.
"""

from __future__ import annotations

from pathlib import Path

from src.settings import DEFAULT_DB


def get_db() -> Path:
    """Return the database path the web layer should read/write.

    Defaults to the project's evaluation-rules DB; tests override it through
    ``app.dependency_overrides[get_db]``.
    """
    return DEFAULT_DB
