"""Shared corpus libraries: libraries, sources, subscriptions, vector chunks.

Change ``add-domain-tree-and-shared-libraries``. Three ideas, one module:

- **Library** — the physical corpus unit (one embedding space + a source list).
  It exists independently of the domain tree: create the library first, then
  let domains subscribe.
- **Source** — one addressable slice of a library (object-store prefix, dataset
  id, …) with its own ingest rule. Ingest runs once per source, never once per
  subscribing domain.
- **Subscription** — a domain's claim on a library (optionally narrowed to a
  subset of its sources). Subscriptions are inherited down the domain tree:
  a child automatically gets its parent's effective sources and may only
  NARROW them. A child may not subscribe a library its parent does not have —
  that would let a sub-domain reach content the parent never granted.

The vector column is ``float4[]`` and similarity is computed in SQL, because
the deployed Postgres image (``postgres:16-alpine``) carries no pgvector
extension. This is a deliberate, documented compromise: the observable contract
(one shared embedding per library, subtree-scoped filtered retrieval) is the
same, and swapping the storage to pgvector later is a local change inside this
module.

There is no migration framework here: every statement must stay idempotent, and
``src.eval.store.ensure_schema`` executes ``LIBRARY_SCHEMA`` on first connect.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from psycopg.types.json import Jsonb

#: Accepted retrieval backends for a library. ``array-cosine`` is what this
#: deployment can actually serve today (no pgvector in the image); the value is
#: stored explicitly so a later backend move is a data change, not a guess.
BACKENDS = ("array-cosine", "pgvector")


LIBRARY_SCHEMA = """
-- ── domain tree ──────────────────────────────────────────────────────────────
-- parent_id + path: a materialized path ('legal', 'legal/contract-review')
-- makes "this domain and its whole subtree" one indexed prefix scan. Depth is
-- small (<=4), so a closure table or recursive CTE would buy nothing.
ALTER TABLE IF EXISTS domains ADD COLUMN IF NOT EXISTS parent_id BIGINT REFERENCES domains(id);
ALTER TABLE IF EXISTS domains ADD COLUMN IF NOT EXISTS path TEXT;

-- Backfill: a pre-tree domain is a root whose path is its own key. Idempotent —
-- only rows that have never been assigned a path are touched again.
UPDATE domains SET path = key WHERE path IS NULL OR path = '';

CREATE UNIQUE INDEX IF NOT EXISTS domains_path_uk ON domains (path);
CREATE INDEX IF NOT EXISTS domains_parent_idx ON domains (parent_id);

-- ── libraries ────────────────────────────────────────────────────────────────
-- dims + backend are frozen per library: changing the embedding model means a
-- new library (and a re-ingest), never a silent in-place dimension change.
CREATE TABLE IF NOT EXISTS libraries (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_key      TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    backend          TEXT NOT NULL DEFAULT 'array-cosine'
                     CHECK (backend IN ('array-cosine', 'pgvector')),
    embedding_model  TEXT,
    dims             INTEGER NOT NULL DEFAULT 2048 CHECK (dims > 0),
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One source = one addressable slice with its own ingest rule. uri is opaque
-- to this module (object-store prefix, dataset id, …); source_kind says which
-- reader to use.
CREATE TABLE IF NOT EXISTS library_sources (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_id   BIGINT NOT NULL REFERENCES libraries(id),
    source_key   TEXT NOT NULL,
    uri          TEXT NOT NULL,
    source_kind  TEXT NOT NULL DEFAULT 'object-prefix',
    content_type TEXT,
    ingest_rule  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (library_id, source_key)
);

-- A subscription is a domain's claim on a library. source_filter NULL means
-- "every source in this library"; an explicit array is the narrowed subset.
-- The narrowing rule (child ⊆ parent) is enforced in effective_sources(), not
-- here: the DB cannot express "start from the parent's set".
CREATE TABLE IF NOT EXISTS domain_library_subscriptions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id     BIGINT NOT NULL REFERENCES domains(id),
    library_id    BIGINT NOT NULL REFERENCES libraries(id),
    source_filter JSONB,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain_id, library_id)
);

-- ── chunks ───────────────────────────────────────────────────────────────────
-- scope_path is the domain path the chunk was ingested FOR (the owning domain
-- that ran the ingest). Retrieval filters on the reader's effective subtree,
-- so one physical chunk serves the whole tree.
CREATE TABLE IF NOT EXISTS corpus_chunks (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_id   BIGINT NOT NULL REFERENCES libraries(id),
    scope_path   TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    doc_path     TEXT NOT NULL,
    chunk_seq    INTEGER NOT NULL,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding    REAL[],
    meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (library_id, doc_path, chunk_seq)
);

CREATE INDEX IF NOT EXISTS corpus_chunks_scope_idx
    ON corpus_chunks (library_id, scope_path);
CREATE INDEX IF NOT EXISTS corpus_chunks_hash_idx
    ON corpus_chunks (library_id, content_hash);

-- ── domain-scoped knowledge units & rubrics ──────────────────────────────────
-- namespace was always the scoping axis (its unique key is
-- (kind, namespace, external_key)); this change makes domain paths the values.
ALTER TABLE IF EXISTS knowledge_units ADD COLUMN IF NOT EXISTS derived_from JSONB;

-- Pre-domain rows were written under the catch-all namespace. Point them at the
-- single pre-existing domain (there is exactly one in every deployed database:
-- the retro-registered legal domain).
UPDATE knowledge_units SET namespace = (
    SELECT path FROM domains ORDER BY id LIMIT 1
) WHERE namespace = 'default';

-- rubrics had no owner at all; evaluation standards are per-domain now.
-- eval_runs learns which rubric (and thus which domain) each run actually used;
-- nullable because legacy runs predate ownership and must not be re-attributed.
ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS rubric_domain_id BIGINT REFERENCES domains(id);
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS domain_id BIGINT REFERENCES domains(id);
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS derived_from BIGINT REFERENCES rubrics(id);
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS fork_diff JSONB;

-- rubrics is created by a legacy schema constant that may run after this one
-- on a fresh database, so the backfill and its index are guarded by existence.
DO $lib$
BEGIN
    IF to_regclass('public.rubrics') IS NOT NULL THEN
        UPDATE rubrics SET domain_id = (
            SELECT id FROM domains ORDER BY id LIMIT 1
        ) WHERE domain_id IS NULL;
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS rubrics_domain_name_uk
                 ON rubrics (domain_id, name)';
    END IF;
END
$lib$;
"""


# ── libraries ────────────────────────────────────────────────────────────────


def create_library(
    conn: Any,
    *,
    library_key: str,
    name: str,
    created_by: str,
    backend: str = "array-cosine",
    embedding_model: Optional[str] = None,
    dims: int = 2048,
) -> dict:
    """Create one library. The key is the stable identity and never changes."""
    library_key = (library_key or "").strip()
    if not library_key:
        raise ValueError("library_key is required")
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {list(BACKENDS)}")
    if not isinstance(dims, int) or dims <= 0:
        raise ValueError("dims must be a positive integer")
    cur = conn.execute(
        """
        INSERT INTO libraries (library_key, name, backend, embedding_model, dims, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, library_key, name, backend, embedding_model, dims, created_by, created_at
        """,
        (library_key, name or library_key, backend, embedding_model, dims, created_by),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return row


def add_source(
    conn: Any,
    *,
    library_key: str,
    source_key: str,
    uri: str,
    created_by: str,
    source_kind: str = "object-prefix",
    content_type: Optional[str] = None,
    ingest_rule: Optional[dict] = None,
) -> dict:
    """Register one source on a library (idempotent per (library, source_key))."""
    lib = get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    cur = conn.execute(
        """
        INSERT INTO library_sources
            (library_id, source_key, uri, source_kind, content_type, ingest_rule, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, source_key, uri, source_kind, content_type, ingest_rule
        """,
        (
            lib["id"],
            source_key,
            uri,
            source_kind,
            content_type,
            Jsonb(ingest_rule or {}),
            created_by,
        ),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return row


def get_library(conn: Any, *, library_key: str) -> Optional[dict]:
    return _row(
        conn.execute(
            "SELECT id, library_key, name, backend, embedding_model, dims FROM libraries "
            "WHERE library_key = %s",
            (library_key,),
        ).fetchone()
    )


def list_libraries(conn: Any) -> list[dict]:
    """Every registered library with its source count, for the console."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT l.id, l.library_key, l.name, l.backend, l.embedding_model, l.dims, "
            "       (SELECT COUNT(*) FROM library_sources s WHERE s.library_id = l.id) "
            "       AS source_count "
            "FROM libraries l ORDER BY l.library_key"
        ).fetchall()
    ]


def list_sources(conn: Any, *, library_id: int) -> list[dict]:
    return [
        _row(r)
        for r in conn.execute(
            "SELECT source_key, uri, source_kind, content_type, ingest_rule "
            "FROM library_sources WHERE library_id = %s ORDER BY source_key",
            (library_id,),
        ).fetchall()
    ]


# ── subscriptions ────────────────────────────────────────────────────────────


def subscribe(
    conn: Any,
    *,
    domain_id: int,
    library_key: str,
    created_by: str,
    source_filter: Optional[Iterable[str]] = None,
) -> dict:
    """Declare (or replace) a domain's subscription to one library.

    ``source_filter=None`` means every source. Narrowing against the parent is
    validated by :func:`effective_sources` — this function only stores the
    claim, because the parent's set may legitimately change later.
    """
    lib = get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    filt = None if source_filter is None else sorted({str(s) for s in source_filter if s})
    known = {s["source_key"] for s in list_sources(conn, library_id=lib["id"])}
    if filt is not None:
        unknown = [s for s in filt if s not in known]
        if unknown:
            raise ValueError(f"unknown source(s) for {library_key!r}: {', '.join(unknown)}")
    cur = conn.execute(
        """
        INSERT INTO domain_library_subscriptions (domain_id, library_id, source_filter, created_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (domain_id, library_id) DO UPDATE
            SET source_filter = excluded.source_filter, created_by = excluded.created_by
        RETURNING id, domain_id, library_id, source_filter
        """,
        (domain_id, lib["id"], None if filt is None else Jsonb(filt), created_by),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return row


def _ancestors(path: str) -> list[str]:
    """``legal/a/b`` → ``['legal', 'legal/a', 'legal/a/b']`` (root first)."""
    parts = [p for p in (path or "").split("/") if p]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def effective_sources(conn: Any, *, domain_path: str) -> dict[str, set[str]]:
    """Resolve a domain's effective retrieval scope.

    Returns ``{library_key: {source_key, …}}``. Rules, applied root → leaf:

    - a root domain's own subscription is its effective set;
    - a child inherits its parent's effective set per library;
    - a child may require a subset (``source_filter``) of an inherited set —
      narrowing only;
    - a child may NOT introduce a library its parent does not have, and may not
      name a source outside the inherited subset.

    Raises ``ValueError`` when a stored subscription violates those rules, so a
    scope can never silently widen.
    """
    path = (domain_path or "").strip().strip("/")
    if not path:
        raise ValueError("domain_path is required")

    rows = conn.execute(
        """
        SELECT d.path, d.id, l.library_key, s.source_filter
          FROM domains d
          JOIN domain_library_subscriptions s ON s.domain_id = d.id
          JOIN libraries l ON l.id = s.library_id
         WHERE d.path = ANY(%s)
        """,
        (_ancestors(path),),
    ).fetchall()
    by_path: dict[str, dict[str, Optional[set[str]]]] = {}
    for r in rows:
        filt = r["source_filter"]
        if isinstance(filt, str):
            filt = json.loads(filt)
        by_path.setdefault(r["path"], {})[r["library_key"]] = (
            None if filt is None else set(filt)
        )

    effective: dict[str, set[str]] = {}
    for ancestor in _ancestors(path):
        own = by_path.get(ancestor, {})
        for lib_key, filt in own.items():
            if lib_key not in effective:
                # First appearance in this chain: it must be a root-level grant.
                if ancestor != _ancestors(path)[0]:
                    raise ValueError(
                        f"library {lib_key!r} is subscribed by {ancestor!r} but not by its parent — "
                        "a sub-domain cannot widen its parent's scope"
                    )
                effective[lib_key] = _library_source_set(conn, lib_key) if filt is None else set(filt)
                continue
            if filt is None:
                continue  # keep inherited set unchanged
            extra = filt - effective[lib_key]
            if extra:
                raise ValueError(
                    f"scope for {ancestor!r} widens library {lib_key!r}: "
                    f"{', '.join(sorted(extra))} not granted by the parent"
                )
            effective[lib_key] = filt
    return effective


def _library_source_set(conn: Any, library_key: str) -> set[str]:
    return {
        r["source_key"]
        for r in conn.execute(
            "SELECT s.source_key FROM library_sources s "
            "JOIN libraries l ON l.id = s.library_id WHERE l.library_key = %s",
            (library_key,),
        ).fetchall()
    }


def _row(row: Any) -> Optional[dict]:
    if row is None:
        return None
    return dict(row) if isinstance(row, dict) else dict(row)
