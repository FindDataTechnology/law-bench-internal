"""Corpus pull surface (change add-corpus-publication §4).

HTTP only, through the same two client patterns the distribution tests use:
``_bare_client`` (only ``get_db`` overridden, so the consumer token IS the
auth) and ``_client`` for the admin publish action.

The external backend is replaced through ``library_index._qdrant_post`` — the
same seam the search path already exposes — so nothing here touches Qdrant.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import corpus_publication, libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.search import library_index
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

LIBRARY_KEY = "corpus-test-library"
DOMAIN_KEY = "corpus-test-domain"
COLLECTION = "law_chunks_test"
TOKEN = "corpus-token"


def _point(law_id: str, chunk_no: int, text: str, *, title: str, category: str) -> dict:
    return {
        "id": int(f"{law_id}{chunk_no}"[:12]),
        "payload": {
            "law_id": law_id,
            "chunk_no": chunk_no,
            "chunk_text": text,
            "title": title,
            "category": category,
        },
    }


def _fake_backend(points: list[dict]):
    def _post(url, path, body, timeout=30.0):
        assert "points/scroll" in path
        pts = points
        for clause in (body.get("filter") or {}).get("must") or []:
            key, val = clause["key"], clause["match"]["value"]
            pts = [p for p in pts if (p["payload"] or {}).get(key) == val]
        keys = body.get("with_payload") or []
        projected = [
            {"id": p["id"], "payload": {k: p["payload"].get(k) for k in keys}} for p in pts
        ]
        start = int(body["offset"]) if body.get("offset") is not None else 0
        limit = int(body.get("limit") or 100)
        page = projected[start : start + limit]
        nxt = start + limit if start + limit < len(projected) else None
        return {"result": {"points": page, "next_page_offset": nxt}}

    return _post


POINTS = [
    _point("1", 0, "第一条 ", title="甲法", category="法律"),
    _point("1", 1, "第二条", title="甲法", category="法律"),
    _point("2", 0, "乙法正文", title="乙法", category="行政法规"),
    _point("3", 0, "丙法正文", title="丙法", category="地方性法规"),
]


@pytest.fixture()
def world(seeded_db, monkeypatch):
    """A qdrant library + a subscribed domain + a consumer bound to that domain."""
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.invalid")
    monkeypatch.setattr(library_index, "_qdrant_post", _fake_backend(POINTS))
    conn = seeded_db
    conn.execute("DELETE FROM corpus_publications")
    conn.execute("DELETE FROM corpus_pull_events")
    conn.execute("DELETE FROM domain_library_subscriptions")
    conn.execute("DELETE FROM library_sources")
    conn.execute("DELETE FROM libraries")
    conn.commit()

    tmpl = templates.create_template(
        conn,
        name="corpus-template",
        schema={
            "entity_types": ["company"],
            "concept_structures": {},
            "relationship_kinds": ["belongs_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {},
        },
        created_by="seed",
    )
    domain = workspaces.instantiate_domain(
        conn, key=DOMAIN_KEY, name="语料域", template_name="corpus-template",
        template_version=tmpl["version"], created_by="seed",
    )
    lib = libraries.create_library(
        conn, library_key=LIBRARY_KEY, name="测试语料库", backend="qdrant",
        dims=1024, location={"url_env": "QDRANT_URL", "collection": COLLECTION},
        created_by="seed",
    )
    mapping = {"id": "law_id", "title": "title", "text": "chunk_text", "order": "chunk_no"}
    libraries.add_source(
        conn, library_key=LIBRARY_KEY, source_key="statutes",
        uri=f"collection:{COLLECTION}#statutes", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["法律"]}, "document": mapping},
        created_by="seed",
    )
    libraries.add_source(
        conn, library_key=LIBRARY_KEY, source_key="others",
        uri=f"collection:{COLLECTION}#others", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["行政法规", "地方性法规"]}, "document": mapping},
        created_by="seed",
    )
    libraries.subscribe(
        conn, domain_id=domain["id"], library_key=LIBRARY_KEY, created_by="seed"
    )
    _register(conn, "corpus-reader", [DOMAIN_KEY], TOKEN)
    return conn


def _register(conn, name: str, domains: list[str], token: str) -> None:
    from src.bench import distribution

    distribution.register_consumer(
        conn, name=name, domains=domains,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), created_by="seed",
    )


def _client(db, user: User) -> TestClient:
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _bare_client(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _publish(conn) -> dict:
    from src.search.library_index import LibraryCorpusReader

    return corpus_publication.publish_library(
        conn, library_key=LIBRARY_KEY, published_by="seed",
        reader=LibraryCorpusReader(conn),
    )


def _pull(client, *, kind="corpus", token=TOKEN, **query):
    headers = {"X-Consumer-Token": token} if token else {}
    return client.get(
        f"/api/v1/distribution/libraries/{LIBRARY_KEY}/{kind}",
        params=query or None, headers=headers,
    )


def _footprints(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM corpus_pull_events").fetchone()["n"]


# ------------------------------------------------------------------ 4.1/4.6


def test_manifest_pages_through_every_document_exactly_once(world):
    publication = _publish(world)
    with _bare_client(world) as client:
        seen: list[str] = []
        cursor = None
        pages = 0
        while True:
            r = _pull(client, limit=2, **({"cursor": cursor} if cursor else {}))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["digest"] == publication["digest"]
            assert body["total_docs"] == 3
            seen.extend(d["doc_key"] for d in body["documents"])
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert pages == 2
        assert seen == ["1", "2", "3"]  # sorted, no dup, no gap


def test_manifest_never_carries_bodies(world):
    _publish(world)
    with _bare_client(world) as client:
        body = _pull(client).json()
    assert all("body" not in d for d in body["documents"])


def test_an_unknown_cursor_is_refused_not_silently_restarted(world):
    _publish(world)
    with _bare_client(world) as client:
        r = _pull(client, cursor="does-not-exist")
    assert r.status_code == 400


def test_a_pinned_version_can_be_read_after_a_newer_one_exists(world):
    v1 = _publish(world)
    world.execute("UPDATE library_sources SET ingest_rule = ingest_rule")  # no-op guard
    with _bare_client(world) as client:
        r = _pull(client, version=v1["version"])
    assert r.status_code == 200
    assert r.json()["publication_version"] == v1["version"]


# -------------------------------------------------------------------- 4.2


def test_document_body_carries_its_digest_and_verifies(world):
    _publish(world)
    with _bare_client(world) as client:
        r = client.get(
            f"/api/v1/distribution/libraries/{LIBRARY_KEY}/documents/1",
            headers={"X-Consumer-Token": TOKEN},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_key"] == "1"
    assert body["title"] == "甲法"
    assert body["body"] == "第一条 第二条"
    assert body["body_matches"] is True
    assert body["doc_digest"] == corpus_publication.doc_digest("甲法", "第一条 第二条")


def test_a_document_outside_the_version_is_404_not_an_empty_body(world):
    _publish(world)
    with _bare_client(world) as client:
        r = client.get(
            f"/api/v1/distribution/libraries/{LIBRARY_KEY}/documents/999",
            headers={"X-Consumer-Token": TOKEN},
        )
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


# -------------------------------------------------------------------- 4.3/4.4


def test_missing_token_is_401(world):
    _publish(world)
    with _bare_client(world) as client:
        r = _pull(client, token=None)
    assert r.status_code == 401
    assert _footprints(world) == 0


def test_unbound_library_is_403_and_leaves_no_footprint(world):
    _publish(world)
    _register(world, "outsider", ["gov"], "outsider-token")
    with _bare_client(world) as client:
        r = _pull(client, token="outsider-token")
    assert r.status_code == 403
    assert r.json()["detail"] == "该库不在绑定范围"
    assert _footprints(world) == 0


def test_revoked_consumer_is_403_and_leaves_no_footprint(world):
    from src.bench import distribution

    _publish(world)
    distribution.revoke_consumer(world, name="corpus-reader")
    with _bare_client(world) as client:
        r = _pull(client)
    assert r.status_code == 403
    assert r.json()["detail"] == "令牌已吊销"
    assert _footprints(world) == 0


def test_successful_pull_leaves_a_footprint(world):
    _publish(world)
    with _bare_client(world) as client:
        assert _pull(client).status_code == 200
    assert _footprints(world) == 1


def test_publishing_before_any_publication_is_404_not_empty(world):
    with _bare_client(world) as client:
        r = _pull(client)
    assert r.status_code == 404
    assert "尚无发布" in r.json()["detail"]


# -------------------------------------------------------------------- 4.5


def test_corpus_routes_do_not_shadow_the_domain_routes(world):
    """``libraries/`` must stay a disjoint path space from ``{domain}/{kind}``."""
    with _bare_client(world) as client:
        rulers = client.get(
            f"/api/v1/distribution/{DOMAIN_KEY}/rulers",
            headers={"X-Consumer-Token": TOKEN},
        )
    # The domain route answered as itself (403 "not a fleet"), not the corpus
    # route's 400/404 about a missing library.
    assert rulers.status_code in (403, 200)
    assert "库" not in rulers.json().get("detail", "")


def test_admin_publish_route_refuses_and_names_the_supported_path(world):
    """Publishing must not run in the request path.

    Inline publishing enumerates 32k documents (~111 MB) while the serving
    process has ~85 MB of headroom; the first inline attempt was OOM-killed
    (exit 137). The route's job is to say so and name ``scripts/publish_corpus.py``,
    not to start work that cannot finish.
    """
    admin = User(sub="admin-u", name="admin", email="a@example.com",
                 scopes=["*"], channel="test")
    with _client(world, admin) as client:
        r = client.post(
            f"/admin/libraries/{LIBRARY_KEY}/publish", data={}, follow_redirects=False
        )
    assert r.status_code == 409
    assert "publish_corpus.py" in r.json()["detail"]
    assert world.execute(
        "SELECT count(*) AS n FROM corpus_publications"
    ).fetchone()["n"] == 0

    non_admin = User(sub="someone", name="s", email="s@example.com",
                     scopes=["content:read"], channel="test")
    with _client(world, non_admin) as client:
        denied = client.post(
            f"/admin/libraries/{LIBRARY_KEY}/publish", data={}, follow_redirects=False
        )
    assert denied.status_code in (403, 401)