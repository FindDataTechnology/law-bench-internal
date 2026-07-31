"""``rag_search`` tool.

Wraps :func:`src.search.query.search` over the Elasticsearch vector store.
Degrades to ``[]`` on any backend failure (mirrors the existing
``ContractSearchTool`` graceful-degradation contract) so a retrieval outage
never raises to the client.
"""

from __future__ import annotations

from ..server import mcp


@mcp.tool
def rag_search(query: str, top_k: int = 5) -> list[dict]:
    """Retrieve ranked clause chunks for a natural-language query.

    Parameters:
        query: natural-language query (Chinese or English).
        top_k: max number of chunks to return (default 5).

    Returns a list of ``{text, source_path, score}``. Returns ``[]`` when
    nothing matches OR when the retrieval backend is unreachable.
    """
    from src.search.query import search

    try:
        return search(query, top_k=top_k)
    except Exception:  # noqa: BLE001 - graceful degradation, never raise
        return []
