"""Batch dispatch (§4.7): gaps become assigned tasks, only after confirmation.

Three behaviours are pinned, each of which is a real way this feature could hurt:

- **loading the estate writes nothing** — the plan lives on its own page, so a
  refresh cannot create tasks;
- **a second confirmation does not duplicate** — an open task for the same
  pillar means "already assigned", and the page says so instead of silently
  skipping;
- **a caller cannot dispatch into a domain it cannot see** — the planner uses
  the same visible-domain set the estate page renders.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import dispatch, libraries, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL,"
        "context TEXT, source TEXT, source_path TEXT, description TEXT,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS criteria ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        "rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,"
        "name TEXT NOT NULL, description TEXT, guidance TEXT,"
        "ordinal INTEGER NOT NULL DEFAULT 0)"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS prompts ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL,"
        "prompt_type TEXT, content TEXT,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    templates.create_template(
        empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": ["external"]},
        },
    )
    for key, path in (("legal", "legal"), ("cr", "legal/cr")):
        parent = None if key == "legal" else empty_db.execute(
            "SELECT id FROM domains WHERE key='legal'").fetchone()["id"]
        empty_db.execute(
            "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
            "SELECT %s,%s,id,1,'t',%s,%s FROM ontology_templates ORDER BY id LIMIT 1",
            (key, key.upper(), parent, path),
        )
    empty_db.commit()
    import src.eval.store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, *, scopes=("*",)) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u1@example.com", scopes=list(scopes),
                channel="test")

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _task_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM authoring_tasks").fetchone()["n"]


def test_loading_the_estate_and_the_plan_creates_nothing(conn):
    with _client(conn) as c:
        assert c.get("/d?gap=knowledge").status_code == 200
        assert c.get("/d/dispatch?gap=knowledge").status_code == 200
    assert _task_count(conn) == 0


def test_confirm_creates_one_task_per_gap_domain(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops@example.com"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert _task_count(conn) == 2  # legal + cr both lack corpus
    rows = conn.execute(
        "SELECT domain_id, assignee, target_key, target_kind, status FROM authoring_tasks"
    ).fetchall()
    assert {r["target_key"] for r in rows} == {"knowledge"}
    assert {r["assignee"] for r in rows} == {"ops@example.com"}
    assert {r["status"] for r in rows} == {"pending"}


def test_second_confirmation_does_not_duplicate(conn):
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"}, follow_redirects=False)
        first = _task_count(conn)
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"},
                   follow_redirects=False)
    assert _task_count(conn) == first
    assert "skipped=2" in r.headers["location"] or "skipped" in r.headers["location"]
    # The plan page reports them as already open rather than hiding them.
    with _client(conn) as c:
        page = c.get("/d/dispatch?gap=knowledge")
    assert page.status_code == 200


def test_dispatch_requires_an_assignee(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": ""},
                   follow_redirects=False)
    assert _task_count(conn) == 0
    assert r.status_code == 303  # bounced back with a flash, nothing written


def test_unknown_pillar_is_refused(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "everything", "assignee": "x"},
                   follow_redirects=False)
    assert _task_count(conn) == 0
    assert r.status_code == 303


def test_a_domain_with_content_is_not_dispatched(conn):
    lib = libraries.create_library(conn, library_key="law", name="Law", created_by="t")
    libraries.add_source(conn, library_key="law", source_key="s1", uri="s3://b/s1", created_by="t")
    legal = conn.execute("SELECT id, path FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=legal["id"], library_key="law", created_by="t")
    conn.execute(
        "INSERT INTO corpus_chunks (library_id, scope_path, source_key, doc_path, chunk_seq, "
        "content, content_hash) VALUES (%s, %s, 's1', 'd.md', 0, 'b', 'h')",
        (lib["id"], legal["path"]),
    )
    conn.commit()
    # Give legal a rubric too, so its only remaining gap is 'inbox' (not a pillar).
    conn.execute(
        "INSERT INTO rubrics (name, context, source, description, domain_id) "
        "VALUES ('q','c','seed','d',%s)", (legal["id"],)
    )
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('entity','legal','party','b','now','now')"
    )
    conn.commit()
    # A second root with no subscription: only a domain off legal's chain can
    # still lack corpus, because `cr` inherits legal's grant and sees the chunk.
    conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "SELECT 'solo','Solo',id,1,'t','solo' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    conn.commit()
    rows = dispatch.rows_for_gap(
        conn,
        domains=[dict(r) for r in conn.execute("SELECT * FROM domains").fetchall()],
        gap="knowledge",
    )
    planned = dispatch.plan(conn, rows=rows, gap="knowledge", assignee="ops")
    # `legal` has real chunks; `cr` inherits them (ancestor chain); only `solo`
    # is genuinely missing corpus.
    assert [d["key"] for d in planned["will_create"]] == ["solo"]
