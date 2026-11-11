"""Tests for ``search_clauses``.

Hermetic: the DB and ``src.search.library_index.search`` are monkeypatched, so no
network and no database. Pins the four-state contract
(knowledge-surface-integrity「读路径三态可判别」+ mcp-error-semantics):

- hits pass through as ``{text, source_path, score}``;
- a valid query with no match is a *successful empty list*;
- a domain with no corpus is ``no_corpus`` / not retryable (未接线);
- a backend failure is ``upstream_unavailable`` / retryable — never an empty list;
- an unknown domain never silently falls back to the default domain.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _FakeConn:
    """Minimal stand-in for a psycopg connection (execute → one row, or none)."""

    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):  # noqa: ARG002 - signature parity
        row = self._row

        class _Cur:
            def fetchone(self_inner):
                return row

        return _Cur()

    def close(self):
        return None


def _patch(monkeypatch, *, domain_row, search_impl):
    """Wire the tool to a fake connection + a fake library search."""
    import src.search.library_index as library_index

    monkeypatch.setattr(library_index, "search", search_impl)

    import src.eval.db as db_mod

    monkeypatch.setattr(db_mod, "connect", lambda db=None: _FakeConn(domain_row))


async def test_rag_returns_chunks(monkeypatch):
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: [
            {"text": "c1", "source_path": "a.md", "score": 0.9}
        ],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("试用期期限", top_k=3)
    assert out == [{"text": "c1", "source_path": "a.md", "score": 0.9}]


async def test_rag_reports_upstream_unavailable_on_failure(monkeypatch):
    """A backend outage is NOT an empty result: it carries a machine-readable code."""

    def boom(conn, *, domain_path, query, top_k=5):
        raise RuntimeError("qdrant unreachable")

    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=boom)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("anything")
    assert out != []
    assert out[0]["error"] == "upstream_unavailable"
    assert out[0]["retryable"] is True
    assert "text" not in out[0], "错误标记不是命中项，不得带 text 字段"


async def test_rag_empty_result_on_no_match(monkeypatch):
    """The other arm: valid query, no match -> successful empty list."""
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: [],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("nothing matches") == []


async def test_unknown_domain_is_no_corpus_and_does_not_fall_back(monkeypatch):
    """An unknown domain must not answer from the default domain."""
    calls: list[str] = []

    def spy(conn, *, domain_path, query, top_k=5):
        calls.append(domain_path)
        return [{"text": "from-legal", "source_path": "x.md", "score": 1.0}]

    _patch(monkeypatch, domain_row=None, search_impl=spy)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", domain="nope")
    assert calls == [], "未知域不得触发任何检索（静默回落＝假命中）"
    assert out[0]["error"] == "no_corpus"
    assert out[0]["retryable"] is False
    assert "text" not in out[0]


async def test_not_subscribed_maps_to_no_corpus(monkeypatch):
    """A registered domain with no subscription is 未接线, not an upstream fault."""
    import src.search.library_index as library_index

    def not_subscribed(conn, *, domain_path, query, top_k=5):
        raise library_index.NotSubscribed("no subscription")

    _patch(monkeypatch, domain_row={"path": "empty-domain"}, search_impl=not_subscribed)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", domain="empty-domain")
    assert out[0]["error"] == "no_corpus"
    assert out[0]["retryable"] is False


async def test_default_domain_matches_web_face(monkeypatch):
    """Both surfaces must search the same corpus when no domain is given."""
    from fd_coding_law_bench_mcp.tools.rag import DEFAULT_DOMAIN

    from src.web.routes.search import DEFAULT_DOMAIN as WEB_DEFAULT

    assert DEFAULT_DOMAIN == WEB_DEFAULT


async def test_blank_query_short_circuits(monkeypatch):
    """Empty query is a no-match, not a backend call."""
    calls: list[str] = []
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: calls.append(query) or [],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("   ") == []
    assert calls == []
