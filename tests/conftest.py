"""Shared pytest fixtures for the chinese-contract-drafter test suite.

Fixtures:
- seeded_db : a throwaway SQLite DB with the real schema (loaded from
  scripts/extract_harbor_rules.py) plus one harbor and one local rubric.
- app_client : a FastAPI TestClient whose ``get_db`` dependency is overridden to
  the throwaway DB, so web tests never touch db/evaluation_rules.db.
- fake_judge : a factory building a deterministic offline ``FakeJudge``.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Legal contract text must not leave the machine; opt out of deepeval telemetry
# for the whole suite (src/eval/run.py sets the same at runtime).
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
# Constructing CrewAI/LiteLLM LLMs otherwise triggers a remote model-cost-map
# fetch; point it at an empty URL so it fails fast and falls back to the local
# copy (keeps the suite hermetic and network-free).
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.web.app import create_app  # noqa: E402
from src.web.deps import get_db  # noqa: E402

from _fakes import FakeJudge  # noqa: E402  (tests/ is on sys.path via conftest)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_extract_module():
    spec = importlib.util.spec_from_file_location(
        "extract_harbor_rules", REPO_ROOT / "scripts" / "extract_harbor_rules.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed_db(db_path: Path) -> None:
    """Create the real schema + one harbor and one local rubric in db_path."""
    extract = _load_extract_module()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    extract.create_schema(conn)
    now = "2026-01-01T00:00:00+00:00"

    # harbor rubric (read-only)
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES ('h_rubric', 'check', 'harbor:v0.20.0', 'p.toml', 'harbor test', ?)",
        (now,),
    )
    h_id = conn.execute("SELECT id FROM rubrics WHERE name = 'h_rubric'").fetchone()[0]
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "VALUES (?, 'h_c1', 'hd', 'hg', 0)",
        (h_id,),
    )

    # local rubric (editable) with two criteria
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES ('l_rubric', 'contract', 'local', NULL, 'local test', ?)",
        (now,),
    )
    l_id = conn.execute("SELECT id FROM rubrics WHERE name = 'l_rubric'").fetchone()[0]
    for i, name in enumerate(["c1", "c2"]):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (?, ?, 'd', 'g', ?)",
            (l_id, name, i),
        )

    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """A throwaway DB with the real schema + one harbor and one local rubric."""
    db_path = tmp_path / "test_rules.db"
    seed_db(db_path)
    return db_path


@pytest.fixture
def app_client(seeded_db: Path) -> TestClient:
    """A TestClient whose web routes read/write the throwaway DB."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fake_judge():
    """Factory building a deterministic offline FakeJudge with given verdicts."""

    def _make(verdicts: list, model_name: str | None = "fake-judge") -> FakeJudge:
        return FakeJudge(verdicts=verdicts, model_name=model_name)

    return _make
