"""``search_clauses`` tool.

Wraps :func:`src.search.library_index.search` — the **same** corpus path the web
face uses: resolve the caller's domain, then for each library that domain
subscribes to, query *that library's own* backend (qdrant / pgvector-external /
owned array-cosine) with the embedding model that built it.

Why not the legacy Elasticsearch path (``src.search.query.search``): this
deployment runs no ES index at all, so the tool answered every query with
``upstream_unavailable`` while 36 万 real statute chunks sat unreachable in
Qdrant (see change ``mcp-clause-search-reads-real-corpus``).

Degradation is honest, not silent — four states, never exceptions, and the
caller can branch on each (knowledge-surface-integrity「读路径三态可判别」,
mcp-error-semantics 四类错误码):

- hit                 ``[{text, source_path, score}]``
- valid, no match     ``[]``
- not wired           ``[{error: "no_corpus", retryable: False, …}]``
                      (this domain subscribes to no corpus at all)
- upstream down       ``[{error: "upstream_unavailable", retryable: True, …}]``

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

#: Machine-readable code for "this domain subscribes to no corpus" — the
#: 未接线 class. NOT retryable: replaying the same call cannot change it.
NO_CORPUS = "no_corpus"

#: The domain searched when the caller names none. MUST match
#: ``src.web.routes.search.DEFAULT_DOMAIN`` — the two surfaces answer the same
#: question, so they must read the same corpus by default.
DEFAULT_DOMAIN = "legal"


def _unavailable_marker(exc: BaseException) -> dict:
    """The single element returned when retrieval could not run at all."""
    return {
        "error": UPSTREAM_UNAVAILABLE,
        "retryable": True,
        "message": f"检索后端不可用，本次未取到结果（{type(exc).__name__}）",
        # Explicitly no `text`/`source_path`: this is not a hit.
    }


def _no_corpus_marker(domain: str) -> dict:
    """The single element returned when the domain has no corpus subscribed."""
    return {
        "error": NO_CORPUS,
        "retryable": False,
        "message": f"域 {domain!r} 未登记任何 RAG 语料（未接线），本次未检索",
        # Explicitly no `text`/`source_path`: this is not a hit.
    }


def _domain_path(conn, domain: str) -> str | None:
    """Return the stored path for ``domain``, or ``None`` when unregistered.

    Unregistered is NOT a reason to fall back to the default domain: silently
    answering from another domain would look exactly like a hit.
    """
    row = conn.execute("SELECT path FROM domains WHERE key = %s", (domain,)).fetchone()
    if not row:
        return None
    path = row["path"] if isinstance(row, dict) else row[0]
    return (path or "").strip() or None


@mcp.tool(tags={"search"}, annotations=annotations_for("search_clauses"))
async def search_clauses(
    query: str,
    top_k: int = 5,
    domain: str | None = None,
) -> list[dict]:
    """Retrieve ranked clause chunks for a natural-language query.

    Parameters:
        query: natural-language query (Chinese or English).
        top_k: max number of chunks to return (default 5).
        domain: domain key to search; omitted ⇒ the same default the web face
            uses (``legal``). An unknown domain returns ``no_corpus`` rather
            than quietly searching another one.

    Returns a list of ``{text, source_path, score}``. Returns ``[]`` when the
    query is valid but nothing matches. Returns a single marker element when
    retrieval could not run: ``{error: "no_corpus", retryable: false, …}`` for a
    domain with no corpus subscribed, ``{error: "upstream_unavailable",
    retryable: true, …}`` when the backend itself failed. Never raises.
    """
    if not (query or "").strip():
        return []

    target = (domain or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN

    def _go() -> list[dict]:
        from src.eval.db import connect
        from src.search import library_index

        conn = connect()  # borrowed/shared connection; close() below is a no-op
        try:
            path = _domain_path(conn, target)
            if path is None:
                return [_no_corpus_marker(target)]
            hits = library_index.search(
                conn, domain_path=path, query=query, top_k=top_k
            )
            return [
                {
                    "text": h.get("text") or "",
                    "source_path": h.get("source_path") or "unknown",
                    "score": h.get("score"),
                }
                for h in hits
            ]
        except library_index.NotSubscribed:
            return [_no_corpus_marker(target)]
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            return [_unavailable_marker(exc)]
        finally:
            conn.close()

    return await anyio.to_thread.run_sync(_go)
