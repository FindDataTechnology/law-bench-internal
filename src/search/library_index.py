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

**External libraries** (``qdrant`` / ``pgvector-external``) are read where they
already live: 364,916 law chunks in Qdrant and the text engine's pgvector
verticals are far too large to copy, and they are maintained by their own
pipelines. For those, the source filter — not ``scope_path`` — is the access
control: a subscriber sees exactly the sources its chain granted, and nothing is
ingested locally. Each library embeds its query with **its own** model
(``src.search.embedders``) because equal dims does not mean equal space.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable, Iterable, Optional

import httpx

from src.bench import libraries
from src.search import embedders as _embedders

#: How many filtered rows a single search is willing to rank in Python. Sized
#: for "one library, a few hundred thousand chunks, filtered to a subtree"; past
#: this the backend (not this function) has to change.
MAX_RANK_ROWS = 20_000

_TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

#: HTTP seam for external stores. Tests replace it to state the protocol without
#: a network; production uses plain httpx.
_http_post = httpx.post


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
    embed: Optional[Callable[[list[str]], list[list[float]]]] = None,
    top_k: int = 5,
) -> list[dict]:
    """Cosine search restricted to a domain's effective subscription scope.

    ``embed`` overrides the per-library embedder (kept for callers that already
    hold vectors and for tests); by default each library is queried with the
    model that built it.

    Raises :class:`NotSubscribed` when the domain resolves to no source at all —
    the caller must be able to tell "nothing to search" from "no match".
    """
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    if not scope:
        raise NotSubscribed(f"domain {domain_path!r} has no library subscription")
    if not (query or "").strip():
        return []

    results: list[dict] = []
    for library_key, allowed in scope.items():
        lib = libraries.get_library(conn, library_key=library_key)
        if lib is None:
            continue
        # A library whose sources are all text tables holds no vectors: it exists
        # for extraction, and asking it for neighbours would either fail on the
        # embedder or return nothing. Skip it rather than fail the whole search —
        # one line's dead weight must not take another line's retrieval down.
        if _text_only(conn, lib):
            continue
        # One embedder per library: several libraries may each live in a
        # different space, so a single query vector for all of them is wrong.
        embed_fn = embed or _embedders.embedder_for_library(lib)
        qvec = embed_fn([query])[0]
        backend = lib.get("backend") or "array-cosine"
        if backend == "qdrant":
            results.extend(_search_qdrant(conn, lib=lib, allowed=allowed,
                                          qvec=qvec, top_k=top_k))
        elif backend == "pgvector-external":
            results.extend(_search_external_pg(conn, lib=lib, allowed=allowed,
                                               qvec=qvec, top_k=top_k))
        else:
            results.extend(_search_owned(conn, lib=lib, domain_path=domain_path,
                                         allowed=allowed, qvec=qvec))
    results.sort(key=lambda h: h["score"], reverse=True)
    return results[: max(1, top_k)]


def _text_only(conn: Any, lib: dict) -> bool:
    """True when a library's sources are text tables — nothing to search."""
    sources = libraries.list_sources(conn, library_id=lib["id"])
    return bool(sources) and all(s.get("source_kind") == "text-table" for s in sources)


def _search_owned(
    conn: Any, *, lib: dict, domain_path: str, allowed: set[str], qvec: list[float]
) -> list[dict]:
    """Score this database's own ``corpus_chunks`` for one library."""
    params: list[Any] = [lib["id"], _scope_paths(domain_path)]
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
    rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

    out = []
    for r in rows:
        emb = r.get("embedding")
        if isinstance(emb, str):  # defensive: some drivers hand back the text form
            emb = [float(x) for x in emb.strip("{}").split(",") if x]
        score = _cosine(qvec, list(emb or []))
        out.append(
            {
                "text": r["content"],
                "source_path": r["doc_path"],
                "score": round(score, 6),
                "source_key": r["source_key"],
                "chunk_seq": r["chunk_seq"],
                "scope_path": r["scope_path"],
                "library_key": lib["library_key"],
            }
        )
    return out


# ── external stores ──────────────────────────────────────────────────────────


def qdrant_filter(sources: list[dict], allowed: Optional[set[str]]) -> Optional[dict]:
    """Translate library sources into one Qdrant payload filter.

    A source's ``ingest_rule`` looks like ``{"match": {"category": "行政法规"}}``
    — every key/value pair must match. A **list** value means "any of these",
    because the corpus spells the same class more than one way (地方性法规 and
    地方法规 are 166,428 points between them; neither name alone is the class).

    Allowed sources are OR-ed (``should``); if any allowed source carries no rule
    it means "the whole collection", which makes the filter unnecessary.

    Returning ``None`` means "no filter" and must only happen when the caller's
    granted set really is the whole collection.

    An empty ``allowed`` set means *unrestricted*, matching the owned backends
    (``_search_owned`` skips the source filter when the set is empty) — so it
    degenerates to "no filter", not to "OR of every source rule": the two differ
    for a library whose sources do not cover the whole collection. Getting this
    backwards is not cosmetic: treating "no narrowing" as "nothing granted" made
    the library-wide count report 0 of 364,916 while the per-source counts summed
    to the full collection.
    """
    if not allowed:
        return None
    branches: list[dict] = []
    for src in sources:
        if src["source_key"] not in allowed:
            continue
        rule = src.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        match = rule.get("match") or {}
        if not match:
            return None
        must = []
        for key, value in sorted(match.items()):
            if isinstance(value, (list, tuple, set)):
                values = [v for v in value]
                if not values:
                    continue
                must.append({"key": str(key), "match": {"any": values}})
            else:
                must.append({"key": str(key), "match": {"value": value}})
        branches.append({"must": must})
    if not branches:
        # Nothing granted: an impossible filter beats an unfiltered search.
        return {"must": [{"key": "source_key", "match": {"value": "__none__"}}]}
    if len(branches) == 1:
        return branches[0]
    # Qdrant's `should` is OR: any granted source's match may hit.
    return {"should": branches}


def _qdrant_post(url: str, path: str, body: dict, timeout: float = 30.0) -> dict:
    resp = _http_post(f"{url.rstrip('/')}{path}", json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _search_qdrant(
    conn: Any, *, lib: dict, allowed: set[str], qvec: list[float], top_k: int
) -> list[dict]:
    loc = libraries.resolve_location(lib)
    url = loc["url_env"]
    collection = loc["collection"]
    filt = qdrant_filter(libraries.list_sources(conn, library_id=lib["id"]), allowed)
    body: dict[str, Any] = {
        "vector": list(qvec),
        "limit": max(1, top_k),
        "with_payload": True,
    }
    if filt is not None:
        body["filter"] = filt
    data = _qdrant_post(url, f"/collections/{collection}/points/search", body)
    sources = libraries.list_sources(conn, library_id=lib["id"])
    out = []
    for hit in data.get("result") or []:
        payload = hit.get("payload") or {}
        title = payload.get("title") or ""
        chunk_no = payload.get("chunk_no")
        out.append(
            {
                "text": payload.get("chunk_text") or "",
                "source_path": f"{title}#{chunk_no}" if title else str(hit.get("id")),
                "score": round(float(hit.get("score") or 0.0), 6),
                "source_key": _source_for_payload(sources, payload),
                "chunk_seq": chunk_no,
                "scope_path": None,
                "library_key": lib["library_key"],
                "meta": payload,
            }
        )
    return out


def _source_for_payload(sources: list[dict], payload: dict) -> str:
    """Which library source a hit belongs to (the reverse of the payload filter).

    Derived from the payload rather than by asking Qdrant to echo the filter:
    the source a chunk came from decides its attribution in the console, and it
    must be the same rule that decided the chunk was in scope.
    """
    for src in sources:
        rule = src.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        match = rule.get("match") or {}
        if not match:
            continue
        hit = True
        for key, expected in match.items():
            actual = payload.get(key)
            if isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    hit = False
                    break
            elif actual != expected:
                hit = False
                break
        if hit:
            return src["source_key"]
    return ""


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _search_external_pg(
    conn: Any, *, lib: dict, allowed: set[str], qvec: list[float], top_k: int
) -> list[dict]:
    """Filtered ``<=>`` search over a pgvector table this app does not own.

    ``uri`` names the table; ``ingest_rule`` may carry ``{"where": {...}}`` for
    equality filters. Both are validated/shape-checked because the table name
    cannot be parameterised.
    """
    import psycopg

    loc = libraries.resolve_location(lib)
    sources = [s for s in libraries.list_sources(conn, library_id=lib["id"])
               if not allowed or s["source_key"] in allowed]
    out: list[dict] = []
    with psycopg.connect(loc["dsn_env"], connect_timeout=10) as ext:
        for src in sources:
            table = src["uri"]
            if not _IDENT.match(table or ""):
                raise ValueError(f"source {src['source_key']!r} has an unsafe table name: {table!r}")
            rule = src.get("ingest_rule") or {}
            if isinstance(rule, str):
                import json as _json

                rule = _json.loads(rule or "{}")
            where = rule.get("where") or {}
            # Similarity search needs a vector column. A source without one is a
            # text table: say so by name instead of letting Postgres answer with
            # 字段 "embedding" 不存在.
            if "embedding" not in table_columns(ext, table):
                raise ValueError(
                    f"source {src['source_key']!r} points at {table!r}, which has no "
                    "'embedding' column — register it with source_kind 'text-table' "
                    "instead of searching it"
                )
            clauses = ["embedding IS NOT NULL"]
            params: list[Any] = []
            for col, val in sorted(where.items()):
                if not _IDENT.match(col):
                    raise ValueError(f"unsafe filter column: {col!r}")
                clauses.append(f"{col} = %s")
                params.append(val)
            sql = (
                f"SELECT chunk_text, chunk_no, document_id, embedding <=> %s::vector AS dist "
                f"FROM {table} WHERE {' AND '.join(clauses)} "
                f"ORDER BY embedding <=> %s::vector LIMIT %s"
            )
            args = [list(qvec), *params, list(qvec), max(1, top_k)]
            for row in ext.execute(sql, tuple(args)).fetchall():
                text, chunk_no, doc_id, dist = row
                out.append(
                    {
                        "text": text or "",
                        "source_path": f"{src['source_key']}#{doc_id}:{chunk_no}",
                        "score": round(1.0 - float(dist), 6),
                        "source_key": src["source_key"],
                        "chunk_seq": chunk_no,
                        "scope_path": None,
                        "library_key": lib["library_key"],
                    }
                )
    return out


def count_for(conn: Any, *, lib: dict, allowed: set[str], chain: list[str]) -> int:
    """Count one library's retrievable chunks for a reader on ``chain``.

    Split out of :func:`count_scope` so a caller that already has per-source
    numbers (the knowledge page) does not pay for a second full scan of the same
    store — two exact counts over 364k points is most of a second.
    """
    backend = lib.get("backend") or "array-cosine"
    if backend == "qdrant":
        return _count_qdrant(conn, lib=lib, allowed=allowed)
    if backend == "pgvector-external":
        return _count_external_pg(conn, lib=lib, allowed=allowed)
    params: list[Any] = [lib["id"], chain]
    sql = ("SELECT COUNT(*) AS n FROM corpus_chunks "
           "WHERE library_id = %s AND scope_path = ANY(%s)")
    if allowed:
        sql += " AND source_key = ANY(%s)"
        params.append(sorted(allowed))
    return conn.execute(sql, tuple(params)).fetchone()["n"]


def count_scope(conn: Any, *, domain_path: str, cache: Optional[dict] = None) -> dict:
    """How much retrievable content a domain's scope actually holds.

    Owned libraries are counted in ``corpus_chunks``; external libraries are
    counted **in their own store**, because a subscription to 364,916 law chunks
    that reports "0 chunks" would be exactly the false gap the estate matrix
    exists to prevent. A store that cannot be reached reports its error instead
    of a zero.

    ``cache`` is a **per-request** memo shared by callers that loop over many
    domains (the estate matrix). An external library's count depends only on
    ``(library, granted sources)`` — not on the reader's path — so ten
    sub-domains inheriting the same grant need one round trip, not ten. Owned
    counts stay uncached: they depend on the reader's ancestor chain.
    """
    out = {"chunks": 0, "by_library": {}, "errors": []}
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    chain = _scope_paths(domain_path)
    for library_key, allowed in scope.items():
        lib = libraries.get_library(conn, library_key=library_key)
        if lib is None:
            continue
        backend = lib.get("backend") or "array-cosine"
        cache_key = (library_key, tuple(sorted(allowed))) if cache is not None else None
        if cache_key is not None and cache_key in cache:
            n = cache[cache_key]
            out["chunks"] += n
            out["by_library"][library_key] = n
            continue
        try:
            n = count_for(conn, lib=lib, allowed=allowed, chain=chain)
            if cache_key is not None and backend in ("qdrant", "pgvector-external"):
                cache[cache_key] = n
            out["chunks"] += n
            out["by_library"][library_key] = n
        except Exception as exc:  # unreachable store must not read as "empty"
            out["errors"].append(f"{library_key}: {exc}")
    return out


def _source_counts_owned(conn: Any, *, lib: dict, sources: list[dict]) -> dict[str, int]:
    """Per-source counts for content ingested into this database (one GROUP BY)."""
    permitted = sorted({s["source_key"] for s in sources})
    rows = conn.execute(
        "SELECT source_key, COUNT(*) AS n FROM corpus_chunks "
        "WHERE library_id = %s AND source_key = ANY(%s) GROUP BY source_key",
        (lib["id"], permitted),
    ).fetchall()
    seen = {r["source_key"]: r["n"] for r in rows}
    return {s["source_key"]: seen.get(s["source_key"], 0) for s in sources}


def _source_counts_external_pg(
    conn: Any, *, lib: dict, sources: list[dict]
) -> dict[str, int]:
    """Per-source counts where a source *is* a table on a foreign database."""
    import psycopg

    loc = libraries.resolve_location(lib)
    out: dict[str, int] = {}
    with psycopg.connect(loc["dsn_env"], connect_timeout=10) as ext:
        for src in sources:
            table = src["uri"]
            if not _IDENT.match(table or ""):
                raise ValueError(f"unsafe table name: {table!r}")
            rule = src.get("ingest_rule") or {}
            if isinstance(rule, str):
                import json as _json

                rule = _json.loads(rule or "{}")
            clauses: list[str] = []
            params: list[Any] = []
            if "embedding" in table_columns(ext, table):
                # Only a vector table can be filtered on having a vector; a text
                # table has no such column and every row counts.
                clauses.append("embedding IS NOT NULL")
            for col, val in sorted((rule.get("where") or {}).items()):
                if not _IDENT.match(col):
                    raise ValueError(f"unsafe filter column: {col!r}")
                clauses.append(f"{col} = %s")
                params.append(val)
            sql = f"SELECT COUNT(*) FROM {table}"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            out[src["source_key"]] = int(ext.execute(sql, tuple(params)).fetchone()[0])
    return out


def _count_qdrant(conn: Any, *, lib: dict, allowed: set[str]) -> int:
    loc = libraries.resolve_location(lib)
    filt = qdrant_filter(libraries.list_sources(conn, library_id=lib["id"]), allowed)
    body: dict[str, Any] = {"exact": True}
    if filt is not None:
        body["filter"] = filt
    data = _qdrant_post(loc["url_env"], f"/collections/{loc['collection']}/points/count", body)
    return int((data.get("result") or {}).get("count") or 0)


def _match_values(src: dict) -> dict[str, list[Any]]:
    """A source's rule as ``{payload_key: [allowed values]}`` (lists normalised)."""
    rule = src.get("ingest_rule") or {}
    if isinstance(rule, str):
        import json as _json

        rule = _json.loads(rule or "{}")
    out: dict[str, list[Any]] = {}
    for key, value in (rule.get("match") or {}).items():
        if isinstance(value, (list, tuple, set)):
            out[str(key)] = list(value)
        else:
            out[str(key)] = [value]
    return out


def source_counts(conn: Any, *, lib: dict, allowed: set[str]) -> dict[str, int]:
    """Per-source chunk counts, answered by whatever the backend does best.

    Owned content is one ``GROUP BY`` here; a foreign pgvector store is one
    ``COUNT(*)`` per table; Qdrant is **one** facet request per payload key
    instead of one per source (7 sources × a round trip each is a slow panel for
    no extra truth), falling back to per-source counts when the rules do not
    share a single filter key — a facet cannot answer that shape.

    ``source_counts`` is what makes "narrow the subscription to these sources"
    a decision taken on numbers instead of on source names, so a backend that
    cannot answer must return ``{}`` rather than zeros.
    """
    sources = [s for s in libraries.list_sources(conn, library_id=lib["id"])
               if not allowed or s["source_key"] in allowed]
    if not sources:
        return {}
    backend = lib.get("backend") or "array-cosine"
    # Owned backends keep their chunks in this database: one GROUP BY, no network.
    if backend in ("array-cosine", "pgvector"):
        return _source_counts_owned(conn, lib=lib, sources=sources)
    # External pgvector: a source *is* a table on someone else's database, so
    # counting per source is the only shape available there.
    if backend == "pgvector-external":
        return _source_counts_external_pg(conn, lib=lib, sources=sources)
    if backend != "qdrant":
        return {}

    rules = {s["source_key"]: _match_values(s) for s in sources}
    keys = {tuple(sorted(r)) for r in rules.values()}
    if len(keys) != 1 or not next(iter(keys)):
        # Mixed or keyless rules: no single facet can answer, count per source.
        return {s["source_key"]: _count_qdrant(conn, lib=lib, allowed={s["source_key"]})
                for s in sources}

    key_tuple = next(iter(keys))
    if len(key_tuple) != 1:
        return {s["source_key"]: _count_qdrant(conn, lib=lib, allowed={s["source_key"]})
                for s in sources}
    # A facet groups by ONE payload key; `key_tuple` is the tuple of the keys the
    # rules filter on, so unwrap it only after the width check above.
    key = key_tuple[0]

    loc = libraries.resolve_location(lib)
    data = _qdrant_post(
        loc["url_env"],
        f"/collections/{loc['collection']}/facet",
        {"key": key, "limit": 1000, "exact": True},
    )
    facet = {h["value"]: int(h["count"]) for h in (data.get("result") or {}).get("hits") or []}
    counts: dict[str, int] = {}
    covered: set[Any] = set()
    for src in sources:
        values = rules[src["source_key"]].get(key, [])
        n = 0
        for v in values:
            if v in facet:
                n += facet[v]
                covered.add(v)
        counts[src["source_key"]] = n
    # A value in the facet that belongs to no granted source is unreachable for
    # this subscription; it is not part of any source's count, and the caller
    # reports the difference against the library total.
    return counts


def table_columns(ext: Any, table: str) -> set[str]:
    """The table's column names (one catalog query, cached per call site)."""
    rows = ext.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def _count_external_pg(conn: Any, *, lib: dict, allowed: set[str]) -> int:
    import psycopg

    loc = libraries.resolve_location(lib)
    total = 0
    with psycopg.connect(loc["dsn_env"], connect_timeout=10) as ext:
        for src in libraries.list_sources(conn, library_id=lib["id"]):
            if allowed and src["source_key"] not in allowed:
                continue
            table = src["uri"]
            if not _IDENT.match(table or ""):
                raise ValueError(f"unsafe table name: {table!r}")
            rule = src.get("ingest_rule") or {}
            if isinstance(rule, str):
                import json as _json

                rule = _json.loads(rule or "{}")
            where = rule.get("where") or {}
            # A text table has no vector column; only a real vector table is
            # filtered on "has a vector". Assuming the column exists is what made
            # the guide-cases count raise 字段 "embedding" 不存在.
            clauses = ["embedding IS NOT NULL"] if "embedding" in table_columns(ext, table) else []
            params: list[Any] = []
            for col, val in sorted(where.items()):
                if not _IDENT.match(col):
                    raise ValueError(f"unsafe filter column: {col!r}")
                clauses.append(f"{col} = %s")
                params.append(val)
            sql = f"SELECT COUNT(*) FROM {table}"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            total += int(ext.execute(sql, tuple(params)).fetchone()[0])
    return total


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
    libraries_out = []
    for lib_key, sources in sorted(scope.items()):
        lib = libraries.get_library(conn, library_key=lib_key) or {}
        libraries_out.append(
            {
                "library_key": lib_key,
                "sources": sorted(sources),
                "origin": "own" if lib_key in own_libs else "inherited",
                "inherited_from": None if lib_key in own_libs else ancestors[0],
                # Which space this library lives in. Two libraries with equal
                # `dims` are not necessarily comparable — see embedders.py — so
                # the model travels with the count.
                "backend": lib.get("backend"),
                "dims": lib.get("dims"),
                "embedding_model": lib.get("embedding_model"),
            }
        )
    return {
        "domain_path": domain_path,
        "libraries": libraries_out,
    }


# ── document enumeration (corpus publication) ────────────────────────────────
# add-corpus-publication: publishing freezes "which documents does this library
# hold" as an immutable version. The unit is a DOCUMENT (one law), not a chunk —
# chunk boundaries move with the splitter, and a digest that changes when the
# splitter changes would invalidate every historical version for no content
# change (design D2).
#
# Two passes, deliberately: pass 1 collects identity/metadata only (32k laws ≈ a
# few MB), pass 2 fetches bodies one law at a time and drops each as soon as its
# digest is computed. Peak memory is therefore "one law", not "the corpus" — the
# full body set is ~147 MB and the platform pod is capped at 512 Mi (design D3).

#: Payload keys every enumerable source must declare. The source's own
#: ``ingest_rule.document`` mapping names the real columns; these are the
#: canonical roles the publication layer speaks in.
_DOC_ROLES = ("id", "title", "text", "order")


class DocumentEnumerationError(ValueError):
    """The library's documents cannot be enumerated faithfully (no silent truncation)."""


def _document_rule(src: dict) -> dict:
    """A source's ``ingest_rule.document`` mapping, validated."""
    rule = src.get("ingest_rule") or {}
    if isinstance(rule, str):
        import json as _json

        rule = _json.loads(rule or "{}")
    doc = rule.get("document") or {}
    if not isinstance(doc, dict):
        raise DocumentEnumerationError(
            f"source {src.get('source_key')!r}: ingest_rule.document must be a mapping"
        )
    missing = [role for role in _DOC_ROLES if not doc.get(role)]
    if missing:
        raise DocumentEnumerationError(
            f"source {src.get('source_key')!r}: ingest_rule.document is missing "
            f"{missing} — a library whose documents cannot be identified cannot be published"
        )
    return {role: str(doc[role]) for role in _DOC_ROLES}


def _scroll_qdrant(
    *,
    url: str,
    collection: str,
    payload_keys: list[str],
    page_size: int,
    timeout: float,
    max_seconds: float,
    max_pages: int,
) -> Iterable[list[dict]]:
    """Yield pages of Qdrant points (payload only), never silently truncated.

    Every bound is explicit and enforced here rather than hoped for: exceeding
    the page or wall-clock budget raises instead of returning the pages read so
    far. A truncated enumeration would produce a manifest that describes a
    corpus that does not exist (design D5).
    """
    import time as _time

    started = _time.monotonic()
    offset = None
    pages = 0
    while True:
        body: dict[str, Any] = {
            "limit": page_size,
            "with_payload": payload_keys,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        data = _qdrant_post(
            url, f"/collections/{collection}/points/scroll", body, timeout=timeout
        )
        result = data.get("result") or {}
        yield list(result.get("points") or [])
        pages += 1
        offset = result.get("next_page_offset")
        if offset is None:
            return
        if pages >= max_pages:
            raise DocumentEnumerationError(
                f"corpus enumeration exceeded {max_pages} pages; refusing to publish "
                "a truncated manifest"
            )
        if _time.monotonic() - started > max_seconds:
            raise DocumentEnumerationError(
                f"corpus enumeration exceeded {max_seconds:.0f}s; refusing to publish "
                "a truncated manifest"
            )


def _sources_accepting(payload: dict, rules: dict[str, dict]) -> list[str]:
    """Which sources' ``match`` rules accept this point (empty = unclaimed).

    A point claimed by no source is corpus the library cannot account for; a
    point claimed by two is ambiguous. Both are errors at publish time rather
    than quiet drops — the manifest must describe the whole library.
    """
    hits: list[str] = []
    for source_key, match in rules.items():
        if not match:
            hits.append(source_key)
            continue
        ok = True
        for key, wanted in match.items():
            actual = payload.get(key)
            values = wanted if isinstance(wanted, (list, tuple, set)) else [wanted]
            if actual not in list(values):
                ok = False
                break
        if ok:
            hits.append(source_key)
    return hits


def enumerate_documents(
    conn: Any,
    *,
    lib: dict,
    allowed: Optional[set[str]] = None,
    page_size: int = 4000,
    timeout: float = 60.0,
    max_seconds: float = 300.0,
    max_pages: int = 500,
) -> list[dict]:
    """Enumerate one library's documents by identity — no bodies, no digests.

    Returns ``[{doc_key, title, source_key, chunk_count}, ...]`` sorted by
    ``(source_key, doc_key)``.

    **One pass over the collection**, not one pass per source: the measured
    corpus is 365,938 points and a pass costs ~20s, so seven filtered passes
    would multiply that by seven for no extra truth. Each point is assigned to
    the source whose ``match`` rule accepts it, in Python, using the same rule
    shape :func:`qdrant_filter` compiles.

    Only ``qdrant`` libraries are enumerable in this release; other backends
    raise naming themselves rather than returning ``[]`` (an empty list would
    read as "this library is empty", which is a different and false statement).
    ``allowed`` narrows to a subscriber's granted sources; ``None``/empty means
    the whole library.
    """
    backend = lib.get("backend")
    if backend != "qdrant":
        raise DocumentEnumerationError(
            f"library {lib.get('library_key')!r} uses backend {backend!r}; document "
            "enumeration is implemented for 'qdrant' only"
        )
    sources = [
        s
        for s in libraries.list_sources(conn, library_id=lib["id"])
        if not allowed or s["source_key"] in allowed
    ]
    if not sources:
        raise DocumentEnumerationError(
            f"library {lib.get('library_key')!r} has no sources in scope; nothing to publish"
        )
    mappings = {s["source_key"]: _document_rule(s) for s in sources}
    rules: dict[str, dict] = {}
    for s in sources:
        rule = s.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        rules[s["source_key"]] = dict(rule.get("match") or {})

    # The id/title roles differ per source in principle, so read the union and
    # look each up through its own source's mapping.
    id_keys = {m["id"] for m in mappings.values()}
    title_keys = {m["title"] for m in mappings.values()}
    match_keys = {k for r in rules.values() for k in r}
    payload_keys = sorted(id_keys | title_keys | match_keys)

    loc = libraries.resolve_location(lib)
    docs: dict[str, dict] = {}
    unclaimed = 0
    for page in _scroll_qdrant(
        url=loc["url_env"],
        collection=loc["collection"],
        payload_keys=payload_keys,
        page_size=page_size,
        timeout=timeout,
        max_seconds=max_seconds,
        max_pages=max_pages,
    ):
        for point in page:
            payload = point.get("payload") or {}
            owning = _sources_accepting(payload, rules)
            if not owning:
                unclaimed += 1
                continue
            if len(owning) > 1:
                raise DocumentEnumerationError(
                    f"a chunk is claimed by several sources {sorted(owning)}; "
                    "source rules must partition the library"
                )
            source_key = owning[0]
            mapping = mappings[source_key]
            raw_key = payload.get(mapping["id"])
            if raw_key is None or str(raw_key).strip() == "":
                raise DocumentEnumerationError(
                    f"source {source_key!r}: a chunk carries no {mapping['id']!r} — "
                    "corpus is corrupt, refusing to publish"
                )
            doc_key = str(raw_key)
            current = docs.get(doc_key)
            if current is None:
                docs[doc_key] = {
                    "doc_key": doc_key,
                    "title": str(payload.get(mapping["title"]) or ""),
                    "source_key": source_key,
                    "chunk_count": 1,
                }
            elif current["source_key"] != source_key:
                raise DocumentEnumerationError(
                    f"document {doc_key!r} appears in sources "
                    f"{current['source_key']!r} and {source_key!r}; "
                    "document identity must be unique per library"
                )
            else:
                current["chunk_count"] += 1

    if unclaimed and not docs:
        raise DocumentEnumerationError(
            f"library {lib.get('library_key')!r}: no chunk is claimed by any source — "
            "the collection does not match the registered rules"
        )
    return sorted(docs.values(), key=lambda d: (d["source_key"], d["doc_key"]))


def fetch_document_body(
    *,
    url: str,
    collection: str,
    id_key: str,
    text_key: str,
    order_key: str,
    doc_key: str,
    page_size: int,
    timeout: float,
) -> str:
    """Fetch one document's body by filtering on its identity, in order."""
    body = {
        "limit": page_size,
        "with_payload": [text_key, order_key],
        "with_vector": False,
        "filter": {"must": [{"key": id_key, "match": {"value": doc_key}}]},
    }
    data = _qdrant_post(
        url, f"/collections/{collection}/points/scroll", body, timeout=timeout
    )
    points = list((data.get("result") or {}).get("points") or [])
    # A law with more chunks than one page would be silently cut here; a cut
    # body is a wrong digest, so refuse rather than truncate.
    if len(points) >= page_size:
        raise DocumentEnumerationError(
            f"document {doc_key!r} returned {len(points)} chunks at the page limit; "
            "refusing to digest a possibly truncated body"
        )
    points.sort(key=lambda p: (p.get("payload") or {}).get(order_key) or 0)
    return "".join(str((p.get("payload") or {}).get(text_key) or "") for p in points)


class LibraryCorpusReader:
    """The corpus-publication kernel's backend seam.

    ``src/bench/corpus_publication`` must not import this module — the kernel
    package-boundary gate forbids relative imports that escape ``src/bench``
    (CI caught exactly that). The dependency points this way: the kernel takes a
    *reader object*, and this is the production one.

    **Memory is the binding constraint, not speed.** Measured 2026-11-20 on the
    live corpus inside the web pod: importing the app plus enumerating the
    32,251 documents costs ~111 MB, the container's limit is 512 Mi, and the
    serving process already holds ~426 MB. So this reader materializes ONE
    document's text at a time and never a page of chunks' worth — the first
    attempt to stream a whole page of chunks was OOM-killed (exit 137).

    That makes publishing slow (~34 ms per document, ≈18 min for the corpus),
    which is exactly why publication does not run inside the request path: it
    runs from ``scripts/publish_corpus.py`` in a separate process. A caller that
    has the headroom may still call it inline (tests do).
    """

    def __init__(self, conn: Any, *, page_size: int = 4000, timeout: float = 60.0,
                 max_seconds: float = 3600.0, max_pages: int = 2000):
        self.conn = conn
        self.page_size = page_size
        self.timeout = timeout
        self.max_seconds = max_seconds
        self.max_pages = max_pages

    def iter_documents(self, *, lib: dict):
        """Yield one document at a time: identity, metadata, and its text.

        Identity comes from :func:`enumerate_documents` (one bounded scroll pass
        that keeps only keys/metadata), then each body is fetched individually
        and released before the next. Slower than a single streaming pass by a
        wide margin, and deliberately so: the streaming variant needed a page of
        chunks resident and was OOM-killed in production.

        **Sources and their payload mappings are resolved ONCE here**, not per
        document. The first version called ``document_body`` for each document,
        which re-queried ``library_sources`` every time — measured 2026-11-20 at
        174 ms/document (≈94 minutes for the corpus), against a single Qdrant
        round trip of ~34 ms. The extra DB query per document was most of the
        difference.
        """
        docs = enumerate_documents(
            self.conn, lib=lib, page_size=self.page_size,
            timeout=self.timeout, max_seconds=self.max_seconds,
            max_pages=self.max_pages,
        )
        sources = {
            s["source_key"]: s
            for s in libraries.list_sources(self.conn, library_id=lib["id"])
        }
        mappings = {k: _document_rule(s) for k, s in sources.items()}
        loc = libraries.resolve_location(lib)

        for doc in docs:
            source_key = doc["source_key"]
            mapping = mappings.get(source_key)
            if mapping is None:
                raise DocumentEnumerationError(
                    f"library {lib.get('library_key')!r} no longer has source "
                    f"{source_key!r}; cannot read document {doc['doc_key']!r} faithfully"
                )
            yield {
                **doc,
                "text": fetch_document_body(
                    url=loc["url_env"], collection=loc["collection"],
                    id_key=mapping["id"], text_key=mapping["text"],
                    order_key=mapping["order"], doc_key=doc["doc_key"],
                    page_size=self.page_size, timeout=self.timeout,
                ),
            }

    def document_body(self, lib: dict, doc_key: str, source_key: str) -> str:
        """One document's text, read through ITS OWN source's payload mapping."""
        sources = {
            s["source_key"]: s
            for s in libraries.list_sources(self.conn, library_id=lib["id"])
        }
        source = sources.get(source_key)
        if source is None:
            # A version may outlive the source that produced it. Reading another
            # source's fields would hash the wrong bytes, so refuse.
            raise DocumentEnumerationError(
                f"library {lib.get('library_key')!r} no longer has source "
                f"{source_key!r}; cannot read document {doc_key!r} faithfully"
            )
        mapping = _document_rule(source)
        loc = libraries.resolve_location(lib)
        return fetch_document_body(
            url=loc["url_env"], collection=loc["collection"],
            id_key=mapping["id"], text_key=mapping["text"],
            order_key=mapping["order"], doc_key=doc_key,
            page_size=self.page_size, timeout=self.timeout,
        )


def document_readiness(conn: Any, *, lib: dict) -> list[dict]:
    """Per-source readiness for corpus publication — a hand-off checklist.

    Why this exists: publishing a library needs each source to declare **which
    payload fields identify a document** (``ingest_rule.document``), and that is
    a fact only the corpus's owner knows. The publisher cannot invent it. What it
    CAN do is state precisely, per source, what shape it currently has and which
    of the four roles are missing — so the person filling it in does not have to
    read code or guess at a schema.

    Pure read: no backend calls, no writes. Each item is:

        {source_key, source_kind, ok, shape, missing, expected}
    """
    sources = libraries.list_sources(conn, library_id=lib["id"])
    out: list[dict] = []
    for src in sources:
        rule = src.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        doc = rule.get("document")
        columns = rule.get("columns")  # case-library's shape
        if isinstance(doc, dict) and doc:
            shape = "document"
            missing = [r for r in _DOC_ROLES if not doc.get(r)]
        elif isinstance(columns, dict) and columns:
            # A column mapping exists but under a different key: the roles it
            # names may line up, and saying so is more useful than "missing".
            shape = "columns"
            alias = {"id": "id", "title": "title", "text": "text", "order": "order_by"}
            missing = [
                r for r in _DOC_ROLES
                if not (columns.get(alias[r]) or (r == "order" and columns.get("order_by")))
            ]
        else:
            shape = "none"
            missing = list(_DOC_ROLES)
        out.append(
            {
                "source_key": src["source_key"],
                "source_kind": src.get("source_kind"),
                "ok": not missing,
                "shape": shape,
                "missing": missing,
                "expected": {
                    "document": {
                        "id": "<一行的稳定标识所在列>",
                        "title": "<标题列>",
                        "text": "<正文列>",
                        "order": "<块序数列>",
                    }
                },
            }
        )
    return out
