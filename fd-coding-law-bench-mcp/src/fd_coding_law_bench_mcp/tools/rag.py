"""``search_clauses`` tool.

Wraps :func:`src.search.query.search` over the Elasticsearch vector store.

Degradation is honest, not silent: a backend outage returns a single
machine-readable marker element (:data:`UPSTREAM_UNAVAILABLE`) instead of an
empty list, so the caller can tell "the corpus has nothing" (``[]``) from "the
backend could not be reached". Both are still *results*, never exceptions —
the retrieval outage must not break the client (knowledge-surface-integrity R3,
mcp-error-semantics: 未找到 ≠ 上游不可用).

The CrewAI tool (``src/search/rag_tool.py``) solves the same problem differently
and deliberately: it keeps the empty string — the drafter must proceed — and
leaves the trace in counters plus warning logs (audit 03 §11). Two consumers, two
honest channels: this one talks to a machine caller that can branch on a code,
that one talks to a model that cannot.
"""

from __future__ import annotations

import anyio

from ..annotations import annotations_for
from ..server import mcp

#: Machine-readable code for "the retrieval backend was unreachable". Mirrors the
#: four-class taxonomy in ``mcp-error-semantics``; retryable, unlike a no-match.
UPSTREAM_UNAVAILABLE = "upstream_unavailable"


def _unavailable_marker(exc: BaseException) -> dict:
    """The single element returned when retrieval could not run at all."""
    return {
        "error": UPSTREAM_UNAVAILABLE,
        "retryable": True,
        "message": f"检索后端不可用，本次未取到结果（{type(exc).__name__}）",
        # Explicitly no `text`/`source_path`: this is not a hit.
    }


@mcp.tool(tags={"search"}, annotations=annotations_for("search_clauses"))
async def search_clauses(query: str, top_k: int = 5) -> list[dict]:
    """Retrieve ranked clause chunks for a natural-language query.

    Parameters:
        query: natural-language query (Chinese or English).
        top_k: max number of chunks to return (default 5).

    Returns a list of ``{text, source_path, score}``. Returns ``[]`` when the
    query is valid but nothing matches. Returns a single
    ``{error: "upstream_unavailable", retryable: true, message}`` element when
    the retrieval backend itself is unreachable — the two are distinguishable.
    Never raises.
    """
    from src.search.query import search

    def _go() -> list[dict]:
        try:
            return search(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            return [_unavailable_marker(exc)]

    return await anyio.to_thread.run_sync(_go)
