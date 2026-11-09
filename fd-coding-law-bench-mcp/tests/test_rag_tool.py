"""Tests for ``search_clauses``.

Hermetic: ``src.search.query.search`` is monkeypatched. Verifies chunk mapping
and that a backend failure is reported as an explicit ``upstream_unavailable``
marker rather than an empty list (knowledge-surface-integrity R3).
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_rag_returns_chunks(monkeypatch):
    import src.search.query as query_mod

    monkeypatch.setattr(
        query_mod,
        "search",
        lambda query, top_k=5: [{"text": "c1", "source_path": "a.md", "score": 0.9}],
    )

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("试用期期限", top_k=3)
    assert out == [{"text": "c1", "source_path": "a.md", "score": 0.9}]


async def test_rag_reports_upstream_unavailable_on_failure(monkeypatch):
    """A backend outage is NOT an empty result: it carries a machine-readable code."""
    import src.search.query as query_mod

    def boom(query, top_k=5):
        raise RuntimeError("ES unreachable")

    monkeypatch.setattr(query_mod, "search", boom)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("anything")
    assert out != []
    assert out[0]["error"] == "upstream_unavailable"
    assert out[0]["retryable"] is True
    assert "text" not in out[0], "错误标记不是命中项，不得带 text 字段"


async def test_rag_empty_result_on_no_match(monkeypatch):
    """The other arm: valid query, no match -> successful empty list."""
    import src.search.query as query_mod

    monkeypatch.setattr(query_mod, "search", lambda query, top_k=5: [])

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("nothing matches") == []
