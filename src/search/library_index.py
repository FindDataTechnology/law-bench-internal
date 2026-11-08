"""Library-backed retrieval: ingest into ``corpus_chunks``, search a domain subtree.

Change ``add-domain-tree-and-shared-libraries`` §2. This module is the one
place that turns a **library** into searchable vectors and a **domain** into a
filtered retrieval call:

- ingest runs once per library source, writing ``scope_path`` = the domain that
  ran it, so one physical chunk serves the whole subtree;
- search resolves the caller's *effective* sources (``libraries.effective_sources``
  — parent inheritance, narrowing only) plus the caller's ancestor chain, and
  filters **before** ranking, so a top-k never leaks a sibling's content;
- an unsubscribed domain raises ``NotSubscribed`` instead of returning ``[]``:
  "no match" and "nothing to search" must stay distinguishable.

Similarity is cosine over ``REAL[]`` computed in Python after a SQL-scoped
filter. That is a deliberate compromise: the deployed Postgres image carries no
pgvector (see ``src/bench/libraries.py``), and at this corpus size the filtered
set is small. If a library outgrows it, only ``_rank`` changes.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable, Iterable, Optional

from src.bench import libraries

#: How many filtered rows a single search is willing to rank in Python. Sized
#: for "one library, a few hundred thousand chunks, filtered to a subtree"; past
#: this the backend (not this function) has to change.
MAX_RANK_ROWS = 20_000

_TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class NotSubscribed(ValueError):
    """The domain has no effective library subscription — nothing to search."""


def chunk_text(text: str, *, size: int = 512, overlap: int = 64) -> list[str]:
    """Split into overlapping character windows.

    Simple on purpose: the legal pipeline's markdown-aware splitter stays where
    it is (``src.search.ingest.chunk_documents``); libraries carry their own
    ingest rule, and a window splitter is the neutral default for mixed content.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


def ingest_documents(
    conn: Any,
    *,
    library_key: str,
    scope_path: str,
    source_key: str,
    documents: Iterable[dict],
    embed: Callable[[list[str]], list[list[float]]],
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> dict:
    """Write ``documents`` (``{path, text}``) into a library's chunk table.

    Idempotent per ``(library, doc_path)``: the document's previous chunks are
    deleted first, so re-ingesting never duplicates. Returns counts for the
    round's report — never a silent success.
    """
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    sources = {s["source_key"] for s in libraries.list_sources(conn, library_id=lib["id"])}
    if source_key not in sources:
        raise ValueError(f"source {source_key!r} is not registered on {library_key!r}")

    chunks: list[tuple[str, int, str]] = []
    for doc in documents:
        path = str(doc.get("path") or doc.get("doc_path") or "unknown")
        for seq, piece in enumerate(
            chunk_text(doc.get("text", ""), size=chunk_size, overlap=chunk_overlap)
        ):
            chunks.append((path, seq, piece))
    if not chunks:
        return {"documents": 0, "chunks": 0}

    vectors = embed([c[2] for c in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("embedding count does not match chunk count")
    dims = lib["dims"]
    for v in vectors:
        if len(v) != dims:
            raise ValueError(
                f"embedding dimension {len(v)} != library {library_key!r} dims {dims}"
            )

    touched = {c[0] for c in chunks}
    for path in touched:
        conn.execute(
            "DELETE FROM corpus_chunks WHERE library_id = %s AND doc_path = %s",
            (lib["id"], path),
        )
    for (path, seq, piece), vec in zip(chunks, vectors):
        conn.execute(
            """
            INSERT INTO corpus_chunks
                (library_id, scope_path, source_key, doc_path, chunk_seq,
                 content, content_hash, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (library_id, doc_path, chunk_seq) DO UPDATE
                SET content = excluded.content,
                    content_hash = excluded.content_hash,
                    embedding = excluded.embedding,
                    source_key = excluded.source_key,
                    scope_path = excluded.scope_path
            """,
            (lib["id"], scope_path, source_key, path, seq, piece, _hash(piece), list(vec)),
        )
    conn.commit()
    return {"documents": len(touched), "chunks": len(chunks)}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _scope_paths(domain_path: str) -> list[str]:
    """The reader's ancestor chain, root first.

    Content is ingested once, at the domain that granted it (usually the root),
    so a reader sees chunks whose ``scope_path`` is on its own chain. A
    sibling's content was written under the sibling's path, which is not on this
    chain — that is what makes siblings invisible without duplicating vectors.
    """
    return libraries._ancestors(domain_path)


def search(
    conn: Any,
    *,
    domain_path: str,
    query: str,
    embed: Callable[[list[str]], list[list[float]]],
    top_k: int = 5,
) -> list[dict]:
    """Cosine search restricted to a domain's effective subscription scope.

    Raises :class:`NotSubscribed` when the domain resolves to no source at all —
    the caller must be able to tell "nothing to search" from "no match".
    """
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    if not scope:
        raise NotSubscribed(f"domain {domain_path!r} has no library subscription")
    if not (query or "").strip():
        return []

    rows: list[dict] = []
    for library_key, allowed in scope.items():
        lib = libraries.get_library(conn, library_key=library_key)
        if lib is None:
            continue
        chain = _scope_paths(domain_path)
        params: list[Any] = [lib["id"], chain]
        sql = (
            "SELECT library_id, scope_path, source_key, doc_path, chunk_seq, content, embedding "
            "FROM corpus_chunks WHERE library_id = %s "
            "AND scope_path = ANY(%s)"
        )
        if allowed:
            sql += " AND source_key = ANY(%s)"
            params.append(sorted(allowed))
        sql += " LIMIT %s"
        params.append(MAX_RANK_ROWS)
        rows.extend(dict(r) for r in conn.execute(sql, tuple(params)).fetchall())

    if not rows:
        return []
    qvec = embed([query])[0]
    scored = []
    for r in rows:
        emb = r.get("embedding")
        if isinstance(emb, str):  # defensive: some drivers hand back the text form
            emb = [float(x) for x in emb.strip("{}").split(",") if x]
        scored.append((_cosine(qvec, list(emb or [])), r))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [
        {
            "text": r["content"],
            "source_path": r["doc_path"],
            "score": round(score, 6),
            "source_key": r["source_key"],
            "chunk_seq": r["chunk_seq"],
            "scope_path": r["scope_path"],
        }
        for score, r in scored[: max(1, top_k)]
    ]


def explain_scope(conn: Any, *, domain_path: str) -> dict:
    """Why this domain can see what it sees — same resolver the search uses.

    Returns the effective set plus, per library, whether the grant is the
    domain's own subscription or inherited from an ancestor. Kept in this module
    (next to ``search``) so the explanation cannot drift from the filter.
    """
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    ancestors = libraries._ancestors(domain_path)
    own = conn.execute(
        """
        SELECT l.library_key, s.source_filter
          FROM domains d
          JOIN domain_library_subscriptions s ON s.domain_id = d.id
          JOIN libraries l ON l.id = s.library_id
         WHERE d.path = %s
        """,
        (domain_path,),
    ).fetchall()
    own_libs = {r["library_key"] for r in own}
    return {
        "domain_path": domain_path,
        "libraries": [
            {
                "library_key": lib,
                "sources": sorted(sources),
                "origin": "own" if lib in own_libs else "inherited",
                "inherited_from": None if lib in own_libs else ancestors[0],
            }
            for lib, sources in sorted(scope.items())
        ],
    }
