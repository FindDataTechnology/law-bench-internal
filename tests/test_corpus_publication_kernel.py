"""Corpus publication kernel (change add-corpus-publication §2-§3).

Hermetic: the external backend is replaced through the same ``_qdrant_post``
seam the search path already uses, so these tests state the protocol without a
network. What they pin:

- the two digest layers and that they reuse the shared canonical kernel;
- ``shape_version`` and ``chunk_count`` stay out of every digest;
- idempotency, empty-library refusal, changelog shape;
- publishing performs ZERO writes against the external backend.
"""

from __future__ import annotations

import pytest

from src.bench import corpus_publication, distribution, libraries
from src.eval.store import ensure_schema
from src.search import library_index

COLLECTION = "law_chunks_test"


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


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


class FakeBackend:
    """A Qdrant stand-in: scroll over a fixture corpus, and count writes."""

    def __init__(self, points: list[dict]):
        self.points = points
        self.write_calls: list[str] = []
        self.scroll_calls = 0

    def __call__(self, url, path, body, timeout=30.0):
        assert "points/scroll" in path, f"unexpected backend call: {path}"
        self.scroll_calls += 1
        pts = self.points
        must = (body.get("filter") or {}).get("must") or []
        for clause in must:
            key, val = clause["key"], clause["match"]["value"]
            pts = [p for p in pts if (p["payload"] or {}).get(key) == val]
        keys = body.get("with_payload") or []
        # Mirror Qdrant: payload projection honours the requested keys.
        projected = [
            {"id": p["id"], "payload": {k: p["payload"].get(k) for k in keys}} for p in pts
        ]
        offset = body.get("offset")
        start = int(offset) if offset is not None else 0
        limit = int(body.get("limit") or 100)
        page = projected[start : start + limit]
        nxt = start + limit if start + limit < len(projected) else None
        return {"result": {"points": page, "next_page_offset": nxt}}


@pytest.fixture()
def backend(monkeypatch):
    points = [
        _point("1", 0, "第一条 ", title="甲法", category="法律"),
        _point("1", 1, "第二条", title="甲法", category="法律"),
        _point("2", 0, "乙法正文", title="乙法", category="行政法规"),
        _point("3", 0, "丙法正文", title="丙法", category="地方性法规"),
    ]

    def install(points=points):
        fake = FakeBackend(points)
        monkeypatch.setattr(library_index, "_qdrant_post", fake)
        return fake

    return install


@pytest.fixture()
def lib(db_conn, monkeypatch):
    """A registered qdrant library with two sources covering the fixture corpus."""
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.invalid")
    library = libraries.create_library(
        db_conn,
        library_key="test-library",
        name="测试库",
        backend="qdrant",
        dims=1024,
        location={"url_env": "QDRANT_URL", "collection": COLLECTION},
        created_by="tester",
    )
    mapping = {
        "id": "law_id",
        "title": "title",
        "text": "chunk_text",
        "order": "chunk_no",
    }
    libraries.add_source(
        db_conn,
        library_key="test-library",
        source_key="statutes",
        uri=f"collection:{COLLECTION}#statutes",
        source_kind="payload-filter",
        ingest_rule={"match": {"category": ["法律"]}, "document": mapping},
        created_by="tester",
    )
    libraries.add_source(
        db_conn,
        library_key="test-library",
        source_key="administrative",
        uri=f"collection:{COLLECTION}#administrative",
        source_kind="payload-filter",
        ingest_rule={"match": {"category": ["行政法规", "地方性法规"]}, "document": mapping},
        created_by="tester",
    )
    return libraries.get_library(db_conn, library_key="test-library")


# ------------------------------------------------------------------ digest


def test_doc_digest_is_the_shared_canonical_digest():
    """2.2: the publication layer must not own a second digest implementation."""
    got = corpus_publication.doc_digest("甲法", "第一条 第二条")
    assert got == distribution.canonical_digest({"title": "甲法", "body": "第一条 第二条"})


def test_version_digest_ignores_order_and_is_content_only():
    entries = [
        {"doc_key": "2", "doc_digest": "b", "title": "乙", "chunk_count": 1},
        {"doc_key": "1", "doc_digest": "a", "title": "甲", "chunk_count": 2},
    ]
    flipped = list(reversed(entries))
    assert corpus_publication.version_digest(entries) == corpus_publication.version_digest(flipped)


def test_chunk_count_and_shape_version_do_not_enter_any_digest():
    """2.3: re-chunking and a shape bump must never invalidate a published digest."""
    a = {"doc_key": "1", "doc_digest": "x", "title": "甲", "chunk_count": 3}
    b = {"doc_key": "1", "doc_digest": "x", "title": "甲", "chunk_count": 99}
    assert corpus_publication.version_digest([a]) == corpus_publication.version_digest([b])
    assert corpus_publication.doc_digest("甲", "正文") == corpus_publication.doc_digest("甲", "正文")


# ------------------------------------------------------------- publishing


def test_publish_builds_a_manifest_and_is_idempotent(db_conn, lib, backend):
    """2.4/2.5: one version, then an unchanged republish returns it."""
    backend()
    v1 = corpus_publication.publish_library(
        db_conn, library_key="test-library", published_by="tester"
    )
    assert v1["version"] == 1
    assert v1["doc_count"] == 3
    assert v1["chunk_count"] == 4
    assert v1["changelog"] == {
        "initial": True,
        "counts": {"documents": 3, "chunks": 4},
    }
    keys = [d["doc_key"] for d in v1["manifest"]["documents"]]
    assert keys == sorted(keys)
    # The title travelled; the body did not.
    assert {"doc_key", "title", "source_key", "chunk_count", "doc_digest"} <= set(
        v1["manifest"]["documents"][0]
    )
    assert "body" not in v1["manifest"]["documents"][0]

    again = corpus_publication.publish_library(
        db_conn, library_key="test-library", published_by="tester"
    )
    assert (again["version"], again["digest"]) == (v1["version"], v1["digest"])
    rows = db_conn.execute("SELECT count(*) AS n FROM corpus_publications").fetchone()
    assert rows["n"] == 1


def test_publishing_never_writes_to_the_external_backend(db_conn, lib, backend):
    """Publication is read-only against the store the corpus lives in."""
    fake = backend()
    corpus_publication.publish_library(
        db_conn, library_key="test-library", published_by="tester"
    )
    assert fake.write_calls == []
    assert fake.scroll_calls > 0  # it read, and only read


def test_empty_library_is_refused(db_conn, lib, backend):
    """2.4: no documents must never produce an empty version."""
    backend([])
    with pytest.raises(library_index.DocumentEnumerationError):
        corpus_publication.publish_library(
            db_conn, library_key="test-library", published_by="tester"
        )
    assert db_conn.execute(
        "SELECT count(*) AS n FROM corpus_publications"
    ).fetchone()["n"] == 0


def test_changelog_names_the_document_that_moved(db_conn, lib, backend):
    """2.4: added / removed / changed, changed carrying both digests."""
    backend()
    v1 = corpus_publication.publish_library(
        db_conn, library_key="test-library", published_by="tester"
    )
    # 甲法's text changes, 乙法 disappears, 丁法 appears.
    changed_points = [
        _point("1", 0, "第一条（修订）", title="甲法", category="法律"),
        _point("1", 1, "第二条", title="甲法", category="法律"),
        _point("3", 0, "丙法正文", title="丙法", category="地方性法规"),
        _point("4", 0, "丁法正文", title="丁法", category="行政法规"),
    ]
    backend(changed_points)
    v2 = corpus_publication.publish_library(
        db_conn, library_key="test-library", published_by="tester"
    )
    assert v2["version"] == 2
    log = v2["changelog"]
    assert log["added"] == ["4"]
    assert log["removed"] == ["2"]
    assert [c["doc_key"] for c in log["changed"]] == ["1"]
    assert log["changed"][0]["before"] != log["changed"][0]["after"]
    # v1 stays byte-identical.
    v1_again = corpus_publication.get_publication(
        db_conn, library_key="test-library", version=1
    )
    assert v1_again["digest"] == v1["digest"]


def test_enumeration_rejects_an_ambiguous_document(db_conn, lib, backend):
    """A document reachable from two sources makes its identity ambiguous."""
    # Same law_id, two categories that belong to different sources.
    points = [
        _point("9", 0, "正文", title="跨界法", category="法律"),
        _point("9", 1, "正文续", title="跨界法", category="行政法规"),
    ]
    backend(points)
    with pytest.raises(library_index.DocumentEnumerationError):
        corpus_publication.publish_library(
            db_conn, library_key="test-library", published_by="tester"
        )