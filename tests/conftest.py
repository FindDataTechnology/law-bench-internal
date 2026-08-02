"""Shared pytest fixtures for the chinese-contract-drafter test suite.

Fixtures:
- seeded_db : a live connection to a shared session PostgreSQL DB, reset
  (TRUNCATE ... RESTART IDENTITY) and reseeded with one harbor and one local
  rubric before each test. ``database_url`` is monkeypatched to this DB so code
  that opens its own connection also hits it.
- empty_db : a fresh per-test PostgreSQL DB with no schema (for tests that
  exercise schema creation / harbor self-heal from a clean slate).
- app_client : a FastAPI TestClient whose ``get_db`` dependency is overridden to
  the ``seeded_db`` connection, so web tests never touch the dev database.
- fake_judge : a factory building a deterministic offline ``FakeJudge``.

Hermetic: requires a reachable local PostgreSQL (maintenance DSN derived from
``database_url``) but no Elasticsearch, MinIO, OpenRouter, or LLM endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

load_dotenv()
# Legal contract text must not leave the machine; opt out of deepeval telemetry
# for the whole suite (src/eval/run.py sets the same at runtime).
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
# Constructing CrewAI/LiteLLM LLMs otherwise triggers a remote model-cost-map
# fetch; point it at an empty URL so it fails fast and falls back to the local
# copy (keeps the suite hermetic and network-free).
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.eval.harbor_seed import create_schema  # noqa: E402
from src.web.app import create_app  # noqa: E402
from src.web.deps import get_db  # noqa: E402

from _fakes import FakeJudge  # noqa: E402  (tests/ is on sys.path via conftest)

REPO_ROOT = Path(__file__).resolve().parents[1]

# All tables that may hold seed/test rows - truncated between tests for isolation.
_ALL_TABLES = (
    "eval_criteria_results",
    "eval_runs",
    "compare_runs",
    "criteria",
    "rubrics",
    "prompts",
    "law_info",
    "clauses",
    "contract_artifacts",
)


def _base_dsn() -> str:
    return (
        os.environ.get("database_url")
        or os.environ.get("DATABASE_URL")
        or "postgresql://app:change-me-please@localhost:5432/law_bench"
    )


def _with_db(dsn: str, db_name: str) -> str:
    p = urlparse(dsn)
    return urlunparse(p._replace(path=f"/{db_name}"))


def _maint_dsn() -> str:
    """DSN for the maintenance DB (used to CREATE / DROP per-test databases)."""
    return _with_db(_base_dsn(), "postgres")


_counter = {"n": 0}


def _new_db_name() -> str:
    _counter["n"] += 1
    return f"law_bench_test_{os.getpid()}_{_counter['n']}"


def _create_db(name: str) -> None:
    conn = psycopg.connect(_maint_dsn())
    conn.autocommit = True
    try:
        conn.execute(f'CREATE DATABASE {name}')
    finally:
        conn.close()


def _drop_db(name: str) -> None:
    conn = psycopg.connect(_maint_dsn())
    conn.autocommit = True
    try:
        conn.execute(f'DROP DATABASE IF EXISTS {name}')
    finally:
        conn.close()


def seed_db(conn) -> None:
    """Reset the schema's tables and seed one harbor + one local rubric on ``conn``.

    Truncate + all inserts run as one multi-statement round trip (criteria use
    subqueries against the just-inserted rubrics) to keep the fixture cheap on
    high-RTT connections.
    """
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "TRUNCATE " + ", ".join(_ALL_TABLES) + " RESTART IDENTITY CASCADE; "
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        f"VALUES ('h_rubric', 'check', 'harbor:v0.20.0', 'p.toml', 'harbor test', '{now}'); "
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        f"VALUES ('l_rubric', 'contract', 'local', NULL, 'local test', '{now}'); "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'h_c1', 'hd', 'hg', 0 FROM rubrics WHERE name = 'h_rubric'; "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c1', 'd', 'g', 0 FROM rubrics WHERE name = 'l_rubric'; "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c2', 'd', 'g', 1 FROM rubrics WHERE name = 'l_rubric';"
    )
    conn.commit()


@pytest.fixture(scope="session")
def _session_db_name() -> str:
    """A shared session PostgreSQL DB with the real schema, created once.

    ``database_url`` is pointed at this DB for the whole session so any code that
    opens its own connection (``connect()``) defaults to it; per-test fixtures
    (``seeded_db``/``empty_db``) may override it further.
    """
    from src.eval.store import ensure_schema  # local import to avoid heavy import

    name = _new_db_name()
    _create_db(name)
    dsn = _with_db(_base_dsn(), name)
    os.environ["database_url"] = dsn
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        create_schema(conn)  # rubrics / criteria / prompts
        conn.commit()
    finally:
        conn.close()
    ensure_schema()  # eval_runs / eval_criteria_results / compare_runs (opens from env)
    # Seed the tag_dims vocabulary (from the manifests) into the session DB and
    # load it into the in-memory TAG_VOCAB, so tag tests see the full vocab.
    # tag_dims is intentionally NOT in _ALL_TABLES - it is read-only reference
    # data, seeded once per session and preserved across per-test truncations.
    from src.clauses.seed_manifest import seed_tag_dims
    from src.clauses.tags import load_vocab_from_db

    seed_tag_dims()
    load_vocab_from_db()
    yield name
    _drop_db(name)


@pytest.fixture
def seeded_db(_session_db_name: str, monkeypatch) -> "psycopg.Connection":
    """A connection to the session DB, reset + reseeded per test."""
    dsn = _with_db(_base_dsn(), _session_db_name)
    monkeypatch.setenv("database_url", dsn)
    conn = psycopg.connect(dsn, row_factory=dict_row)
    seed_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def empty_db(monkeypatch) -> "psycopg.Connection":
    """A fresh per-test Postgres DB with no schema (for self-heal / migration tests)."""
    name = _new_db_name()
    _create_db(name)
    dsn = _with_db(_base_dsn(), name)
    monkeypatch.setenv("database_url", dsn)
    conn = psycopg.connect(dsn, row_factory=dict_row)
    yield conn
    conn.close()
    _drop_db(name)


@pytest.fixture
def app_client(seeded_db) -> TestClient:
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
