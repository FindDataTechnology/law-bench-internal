"""The knowledge area can actually retrieve from the corpus it lists (§2 / §4.3).

The estate matrix proved a domain has 364,916 retrievable chunks; until this page
had a search box, no screen could retrieve any of them — `/search` still speaks to
the legacy `rag_corpora` index. These tests pin the three outcomes a caller must
be able to tell apart:

- hits, each attributed to the source that decided it was in scope;
- **no hits** (a miss inside a real corpus);
- **an error** (unreachable store / not subscribed) — never rendered as "no hits".

The Qdrant and embedder HTTP seams are stubbed, so this asserts the protocol the
page depends on rather than the deployment's current hostnames.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import libraries, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.search import embedders, library_index
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


class _Stub:
    def __init__(self, answer):
        self.calls: list[dict] = []
        self._answer = answer

    def __call__(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json})
        payload = self._answer(url, json)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(
        empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": ["external"]},
        },
    )
    empty_db.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "SELECT 'legal','法律域',id,1,'t','legal' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    empty_db.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "SELECT 'bare','空域',id,1,'t','bare' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    embedders.clear_cache()
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setenv(embedders.LOCAL_EMBED_URL_ENV, "http://embed.test:6100")
    yield
    embedders.clear_cache()


def _client(db) -> TestClient:
    app = create_app()
    user = User(sub="w", name="w", email="w@e.com", scopes=["*"], channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _law_library(conn) -> None:
    libraries.create_library(
        conn, library_key="law-library", name="法规大库", created_by="t", backend="qdrant",
        embedding_model="Qwen/Qwen3-Embedding-0.6B", dims=1024,
        location={"url_env": "TEST_QDRANT", "collection": "law_chunks_v2"},
    )
    libraries.add_source(conn, library_key="law-library", source_key="judicial",
                         uri="x", created_by="t", ingest_rule={"match": {"category": "司法解释"}})
    legal = conn.execute("SELECT id FROM domains WHERE key='legal'").fetchone()["id"]
    # Narrowed to the one source this domain is granted; `local` is deliberately
    # not in the set, so the filter must never mention it.
    libraries.subscribe(conn, domain_id=legal, library_key="law-library", created_by="t",
                        source_filter=["judicial"])
    conn.commit()


def _embed_stub() -> _Stub:
    return _Stub(lambda url, body: {"embeddings": [[0.01] * 1024] * len(body["input"])})


def test_hits_are_rendered_with_source_and_locator(conn, monkeypatch):
    _law_library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed_stub())
    monkeypatch.setattr(
        library_index, "_http_post",
        _Stub(lambda url, body: {"result": [
            {"id": 1, "score": 0.7617,
             "payload": {"chunk_text": "关于建设工程价款优先受偿权问题的批复",
                         "title": "批复", "chunk_no": 0, "category": "司法解释"}},
        ]}),
    )
    with _client(conn) as c:
        r = c.get("/d/legal/knowledge?q=建设工程价款优先受偿权")
    assert r.status_code == 200
    assert "关于建设工程价款优先受偿权问题的批复" in r.text
    assert "judicial" in r.text          # attributed to the source
    assert "批复#0" in r.text            # locator
    assert "0.762" in r.text             # score, 3 decimals


def test_no_hits_says_miss_and_not_empty_corpus(conn, monkeypatch):
    _law_library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed_stub())
    monkeypatch.setattr(library_index, "_http_post", _Stub(lambda url, body: {"result": []}))
    with _client(conn) as c:
        r = c.get("/d/legal/knowledge?q=完全不相关的问题")
    assert r.status_code == 200
    assert "不是「没有语料」" in r.text


def test_unreachable_store_is_an_error_not_no_hits(conn, monkeypatch):
    _law_library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed_stub())
    monkeypatch.setattr(
        library_index, "_http_post",
        _Stub(lambda url, body: RuntimeError("connection refused")),
    )
    with _client(conn) as c:
        r = c.get("/d/legal/knowledge?q=条例")
    assert r.status_code == 200
    assert "检索失败" in r.text
    assert "connection refused" in r.text


def test_unsubscribed_domain_reports_that_it_has_no_corpus(conn):
    with _client(conn) as c:
        r = c.get("/d/bare/knowledge?q=条例")
    assert r.status_code == 200
    assert "未订阅" in r.text


def test_page_without_a_query_does_not_search(conn, monkeypatch):
    """Opening the page must cost nothing: no embed call, no store call."""
    _law_library(conn)
    embed_stub = _embed_stub()
    store_stub = _Stub(lambda url, body: {"result": []})
    monkeypatch.setattr(embedders, "_http_post", embed_stub)
    monkeypatch.setattr(library_index, "_http_post", store_stub)
    with _client(conn) as c:
        c.get("/d/legal/knowledge")
    # Opening the page may *count* (that is the blocker number it shows) but it
    # must never embed a query or rank chunks.
    assert embed_stub.calls == []
    assert all("/points/count" in c["url"] for c in store_stub.calls)


def test_search_obeys_the_narrowed_source_set(conn, monkeypatch):
    """A domain granted one source must send a filter naming only that source."""
    _law_library(conn)
    # Add a second source the domain is NOT granted.
    libraries.add_source(conn, library_key="law-library", source_key="local",
                         uri="x", created_by="t", ingest_rule={"match": {"category": "地方性法规"}})
    conn.commit()
    stub = _Stub(lambda url, body: {"result": []})
    monkeypatch.setattr(embedders, "_http_post", _embed_stub())
    monkeypatch.setattr(library_index, "_http_post", stub)
    with _client(conn) as c:
        c.get("/d/legal/knowledge?q=条例")
    body = stub.calls[0]["body"]
    sent = json.dumps(body.get("filter") or {}, ensure_ascii=False)
    assert "司法解释" in sent
    assert "地方性法规" not in sent
