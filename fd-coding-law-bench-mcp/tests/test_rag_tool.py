"""Tests for ``rag_search``.

Hermetic: ``src.search.query.search`` is monkeypatched. Verifies chunk mapping
and graceful degradation to ``[]`` on backend failure.
"""

from __future__ import annotations


def test_rag_returns_chunks(monkeypatch):
    import src.search.query as query_mod

    monkeypatch.setattr(
        query_mod,
        "search",
        lambda query, top_k=5: [{"text": "c1", "source_path": "a.md", "score": 0.9}],
    )

    from fd_coding_law_bench_mcp.tools.rag import rag_search

    out = rag_search("试用期期限", top_k=3)
    assert out == [{"text": "c1", "source_path": "a.md", "score": 0.9}]


def test_rag_degrades_to_empty_on_failure(monkeypatch):
    import src.search.query as query_mod

    def boom(query, top_k=5):
        raise RuntimeError("ES unreachable")

    monkeypatch.setattr(query_mod, "search", boom)

    from fd_coding_law_bench_mcp.tools.rag import rag_search

    assert rag_search("anything") == []
