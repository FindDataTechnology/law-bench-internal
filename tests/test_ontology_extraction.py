"""Candidate extraction (§§1-4): the gates, not the model.

Nothing here calls a model: `complete_fn` is injected. What is pinned is exactly
what a hallucinating model would try to get past — a paraphrased quote, an
out-of-vocabulary kind, a relationship pointing at nothing — plus the two
operational facts an operator needs: re-running is idempotent, and a cap stops
the run loudly.
"""

from __future__ import annotations

import json

import pytest

from src.bench import authoring, extraction, libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites_law"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

CHUNK_TEXT = "第一条 为了规范合同的订立，制定本法。第二条 合同应当采用书面形式。"


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _fake_qdrant(chunks):
    """Return a _post replacement that scrolls the given chunks once."""
    calls = {"n": 0}

    def post(url, path, body, timeout=30.0):
        calls["n"] += 1
        points = [
            {"id": c["chunk_id"],
             "payload": {"chunk_text": c["text"], "title": c.get("title", ""),
                         "law_id": c.get("law_id", 1), "chunk_no": c.get("chunk_no", 0),
                         "category": "法律"}}
            for c in (chunks if calls["n"] == 1 else [])
        ]
        return {"result": {"points": points, "next_page_offset": None}}

    return post, calls


def _library(conn):
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", embedding_model="Qwen/Qwen3-Embedding-0.6B",
                             dims=1024,
                             location={"url_env": "TEST_QDRANT", "collection": "law_chunks_v2"})
    libraries.add_source(conn, library_key="law-library", source_key="statutes",
                         uri="x", created_by="t", ingest_rule={"match": {"category": "法律"}})
    dom = conn.execute("SELECT id FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    conn.commit()
    return dom


def _run(conn, monkeypatch, answer, *, chunks=None, **kw):
    _library(conn)
    chunks = chunks or [{"chunk_id": "c1", "text": CHUNK_TEXT, "title": "某法"}]
    post, calls = _fake_qdrant(chunks)
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    return extraction.run(
        conn, domain_key="legal",
        complete_fn=lambda prompt: answer if isinstance(answer, str) else json.dumps(answer),
        **kw,
    )


def test_good_candidates_land_as_pending_proposals(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "合同法", "chunk_id": "c1", "quote": "为了规范合同的订立"}],
        "relationships": []}
    before = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    report = _run(conn, monkeypatch, answer)
    after = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    assert report["submitted"] == 1 and report["skipped"]["bad_quote"] == 0
    assert after == before, "extraction must never write the ontology"
    rows = conn.execute("SELECT source, evidence, impact FROM domain_proposals").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"].startswith("extract:")
    evidence = rows[0]["evidence"]
    assert evidence["chunk_id"] == "c1" and evidence["batch"]
    assert "原文：" in rows[0]["impact"]


def test_paraphrased_quote_is_dropped(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "合同法", "chunk_id": "c1", "quote": "为了管制合同的签署"}],
        "relationships": []}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0
    assert report["skipped"]["bad_quote"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM domain_proposals").fetchone()["n"] == 0


def test_out_of_vocabulary_kind_is_dropped(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "penalty", "name": "罚款", "chunk_id": "c1", "quote": "合同应当采用书面形式"}],
        "relationships": []}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0 and report["skipped"]["bad_kind"] == 1


def test_relationship_needs_a_closed_endpoint(conn, monkeypatch):
    answer = {"entities": [],
              "relationships": [
                  {"kind": "cites_law", "from_name": "合同法", "to_name": "民法典",
                   "chunk_id": "c1", "quote": "合同应当采用书面形式"}]}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0 and report["skipped"]["bad_endpoint"] == 1


def test_same_batch_entity_closes_the_endpoint(conn, monkeypatch):
    """`A→B` must be proposable when B is nominated in the same batch."""
    answer = {"entities": [
        {"kind": "law", "name": "合同法", "chunk_id": "c1", "quote": "规范合同的订立"},
        {"kind": "law", "name": "民法典", "chunk_id": "c1", "quote": "合同应当采用书面形式"}],
        "relationships": [
        {"kind": "cites_law", "from_name": "合同法", "to_name": "民法典",
         "chunk_id": "c1", "quote": "合同应当采用书面形式"}]}
    report = _run(conn, monkeypatch, answer, max_per_chunk=8)
    assert report["submitted"] == 3
    assert report["skipped"]["bad_endpoint"] == 0


def test_rerun_is_idempotent(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "合同法", "chunk_id": "c1", "quote": "规范合同的订立"}],
        "relationships": []}
    first = _run(conn, monkeypatch, answer)
    assert first["submitted"] == 1
    # The library already exists from _run; only reset the scroll stub so the
    # second run samples the same chunk again.
    post, _ = _fake_qdrant([{"chunk_id": "c1", "text": CHUNK_TEXT, "title": "某法"}])
    monkeypatch.setattr(extraction, "_post", post)
    second = extraction.run(conn, domain_key="legal",
                            complete_fn=lambda p: json.dumps(answer))
    assert second["submitted"] == 0
    assert second["duplicate"] == 1


def test_cap_stops_the_run_and_says_so(conn, monkeypatch):
    chunks = [{"chunk_id": f"c{i}", "text": CHUNK_TEXT, "title": f"法{i}"} for i in range(5)]
    answer = {"entities": [
        {"kind": "law", "name": "甲法", "chunk_id": "c0", "quote": "规范合同的订立"},
        {"kind": "law", "name": "乙法", "chunk_id": "c0", "quote": "合同应当采用书面形式"}],
        "relationships": []}
    _library(conn)
    # each chunk yields the same two candidates but with distinct chunk ids
    def post(url, path, body, timeout=30.0):
        if getattr(post, "done", False):
            return {"result": {"points": []}}
        post.done = True
        return {"result": {"points": [
            {"id": c["chunk_id"], "payload": {"chunk_text": c["text"], "title": c["title"],
                                              "category": "法律"}} for c in chunks]}}
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    report = extraction.run(conn, domain_key="legal", max_chunks=5, max_total=3,
                            complete_fn=lambda p: json.dumps(answer))
    assert report["stopped"] == "cap"
    assert report["produced"] <= 3


def test_no_corpus_is_an_error_not_an_empty_report(conn):
    with pytest.raises(extraction.ExtractionError, match="subscribes to no corpus"):
        extraction.sample_chunks(conn, domain_path="legal")


def test_scope_is_enforced_for_explicit_sources(conn):
    _library(conn)
    with pytest.raises(extraction.ExtractionError, match="not in this domain's scope"):
        extraction.sample_chunks(conn, domain_path="legal", sources=["judicial"])


def test_prompt_carries_the_vocabularies_and_version():
    prompt = extraction.build_prompt(schema=SCHEMA, chunks=[{"chunk_id": "c1", "text": "x",
                                                             "source_key": "statutes", "title": "t"}])
    assert "clause" in prompt and "cites_law" in prompt
    assert extraction.PROMPT_VERSION in prompt


@pytest.mark.parametrize("name,expected", [
    ("中华人民共和国 民法典", "中华人民共和国-民法典"),
    ("民法典（总则）", "民法典-总则"),
    ("  空格  很多  ", "空格-很多"),
])
def test_entity_keys_are_stable(name, expected):
    assert extraction.normalize_entity_key(name) == expected


def test_parse_survives_fences_and_prose():
    raw = '好的，结果如下：\n```json\n{"entities":[{"kind":"law","name":"民法典","quote":"q"}],"relationships":[]}\n```\n以上。'
    parsed = extraction.parse_candidates(raw)
    assert len(parsed["entities"]) == 1 and parsed["bad_rows"] == 0


def test_parse_counts_bad_rows_without_failing():
    raw = json.dumps({"entities": [{"kind": "law", "name": "民法典", "quote": "q"},
                                   {"kind": "law"}], "relationships": []})
    parsed = extraction.parse_candidates(raw)
    assert len(parsed["entities"]) == 1 and parsed["bad_rows"] == 1


def test_sampling_spreads_across_documents():
    """Scroll is ordered by point id, and points are written document by
    document: a naive page of N chunks can be 1–2 laws (measured in production:
    20 chunks from 2 law_ids). `_spread` takes at most 2 per document, round
    robin, so a page covers many documents."""
    chunks = []
    for law in range(1, 6):                     # 5 documents
        for no in range(5):                     # 5 chunks each, consecutive ids
            chunks.append({"chunk_id": f"{law}-{no}", "law_id": law, "text": "t"})
    picked = extraction._spread(chunks, 8)
    assert len(picked) == 8
    assert len({c["law_id"] for c in picked}) == 5      # every document represented
    # Never more than two per document on the first pass.
    from collections import Counter
    assert max(Counter(c["law_id"] for c in picked).values()) <= 2


def test_spread_returns_everything_when_the_page_is_large_enough():
    chunks = [{"chunk_id": f"{law}-0", "law_id": law, "text": "t"} for law in range(3)]
    assert len(extraction._spread(chunks, 10)) == 3


def test_spread_tolerates_a_document_rich_window():
    """If one document dominates the window, fill the page from it rather than
    returning a short page."""
    chunks = [{"chunk_id": f"1-{i}", "law_id": 1, "text": "t"} for i in range(10)]
    picked = extraction._spread(chunks, 4)
    assert len(picked) == 4
