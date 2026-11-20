"""Versioned publication of a corpus library (change ``add-corpus-publication``).

The blueprint promised three publishable classes. Ontology has
``knowledge-distribution``; rulers and gold samples have
``add-typed-publications``. This module is the third: **the retrieval corpus**.

Why the unit is a library and not a domain: a corpus is the shared physical
layer ("一次投入、多域取材" — ``shared-corpus-library``). The same ``law-library``
is subscribed by ``legal`` and ``gov``; numbering versions per domain would give
two consumers two digests for one unchanged corpus, and the only purpose of a
digest is to be checked against someone else's copy.

Why the unit is a document and not a chunk: chunk boundaries and ordinals are
the splitter's output. Freezing chunks would invalidate every historical digest
the day the splitter is tuned, while not one character of content changed.

Why the digest is two layers: the corpus body is ~147 MB of canonical JSON and
the platform process is capped at 512 Mi. Per-document digests keep peak memory
at "one document plus a 32k-entry key list" (~3 MB) — see design D3.

Both layers call :func:`src.bench.distribution.canonical_digest`, the one
canonical-serialization kernel. A second digest implementation would let two
surfaces disagree about what "the same corpus" means.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Writes commit once, at the end.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import distribution, libraries
from .distribution import canonical_digest

#: Projection shape version. Lives BESIDE every digest, never inside one — a
#: shape bump must not invalidate digests already handed out (design D3).
SHAPE_VERSION = 1

#: Fields each manifest entry carries. ``chunk_count`` is deliberately NOT part
#: of the document digest: it is the splitter's product. It still travels in the
#: manifest so a consumer can notice that re-chunking happened.
ENTRY_FIELDS = ("doc_key", "title", "chunk_count", "doc_digest")

_PUBLICATION_COLS = (
    "id, library_id, version, digest, shape_version, manifest, changelog, "
    "doc_count, chunk_count, published_by, published_at"
)
_PUBLICATION_KEYS = (
    "id",
    "library_id",
    "version",
    "digest",
    "shape_version",
    "manifest",
    "changelog",
    "doc_count",
    "chunk_count",
    "published_by",
    "published_at",
)


class NothingToPublish(ValueError):
    """The library has no documents in scope; an empty version must never land."""


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _iso(val: Any) -> Any:
    return val.isoformat() if hasattr(val, "isoformat") else val


def _publication_to_dict(row: Any) -> dict:
    values = [row[k] for k in _PUBLICATION_KEYS] if isinstance(row, dict) else list(row)
    return {
        "id": values[0],
        "library_id": values[1],
        "version": values[2],
        "digest": values[3],
        "shape_version": values[4],
        "manifest": _decode_jsonb(values[5]),
        "changelog": _decode_jsonb(values[6]),
        "doc_count": int(values[7]),
        "chunk_count": int(values[8]),
        "published_by": values[9],
        "published_at": _iso(values[10]),
    }


# ---------------------------------------------------------------- digest


def doc_digest(title: str, body: str) -> str:
    """One document's content anchor.

    Covers the title and the concatenated body, nothing else: not the chunk
    ordinals, not the source key, not the library. Measured on the live corpus,
    consecutive chunks of a document do not overlap and their ``chunk_no`` is
    contiguous, so concatenation is exactly "the document's text"; a future
    splitter that overlaps windows would make the concatenation depend on the
    splitter again — at that point the body must be serialized as the ordered
    chunk list instead (the digest then still covers content, not ordinals).
    """
    return canonical_digest({"title": str(title or ""), "body": str(body or "")})


def version_digest(entries: list[dict]) -> str:
    """The version anchor: the sorted ``(doc_key, doc_digest)`` list.

    Sorting by ``doc_key`` makes the digest a pure function of content — the
    order documents happen to be enumerated in cannot change it. Titles and
    chunk counts stay out: a retitled-but-identical document is a different
    document for a reader, and title IS inside ``doc_digest``; chunk count is
    the splitter's.
    """
    pairs = [{"doc_key": e["doc_key"], "doc_digest": e["doc_digest"]} for e in entries]
    pairs.sort(key=lambda p: p["doc_key"])
    return canonical_digest({"documents": pairs})


# ------------------------------------------------------------- projection


def build_manifest(conn: Any, *, lib: dict, reader: Any) -> dict:
    """Project the library's documents into a publishable manifest.

    ``reader`` is the *caller-supplied* backend accessor — the kernel must not
    reach into ``src.search`` (kernel package-boundary gate: a relative import
    that escapes ``src/bench`` is a violation, and CI caught exactly that).

        for doc in reader.iter_documents(lib=lib):
            doc["doc_key"], doc["title"], doc["source_key"],
            doc["chunk_count"], doc["text"]

    **One streaming pass**, not "enumerate then fetch each body": the first
    implementation did one round trip per document, and on the live corpus that
    is 32,251 requests × ~34 ms ≈ 18 minutes (measured 2026-11-20 *after* the
    rehearsal timed out). Streaming keeps the same peak memory — one document's
    text at a time — while paying for a single pass over the collection.
    """
    entries: list[dict] = []
    for doc in reader.iter_documents(lib=lib):
        entries.append(
            {
                "doc_key": doc["doc_key"],
                "title": doc["title"],
                # The source travels with the entry so a later document read can
                # use THAT source's payload mapping; guessing the mapping from a
                # sibling source would read the wrong field and hash the wrong
                # bytes (a wrong digest is worse than a failed read).
                "source_key": doc["source_key"],
                "chunk_count": doc["chunk_count"],
                "doc_digest": doc_digest(doc["title"], doc["text"]),
            }
        )
    if not entries:
        raise NothingToPublish(
            f"library {lib.get('library_key')!r} has no documents to publish"
        )
    entries.sort(key=lambda e: e["doc_key"])
    return {
        "library_key": lib["library_key"],
        "documents": entries,
        "total_docs": len(entries),
        "total_chunks": sum(e["chunk_count"] for e in entries),
    }


# --------------------------------------------------------------- changelog


def diff_manifests(old: Optional[dict], new: dict) -> dict:
    """Added / removed / changed, keyed by ``doc_key``.

    Same shape as the other publication kinds' changelogs so one console branch
    renders all of them. ``changed`` carries the old and new document digest —
    that is the only fact a consumer needs to know which law moved.
    """
    counts = {
        "documents": new.get("total_docs", len(new.get("documents") or [])),
        "chunks": new.get("total_chunks", 0),
    }
    if old is None:
        return {"initial": True, "counts": counts}
    before = {e["doc_key"]: e for e in old.get("documents") or []}
    after = {e["doc_key"]: e for e in new.get("documents") or []}
    changed = [
        {
            "doc_key": key,
            "before": before[key]["doc_digest"],
            "after": after[key]["doc_digest"],
        }
        for key in sorted(before.keys() & after.keys())
        if before[key]["doc_digest"] != after[key]["doc_digest"]
    ]
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": changed,
        "counts": counts,
    }


# -------------------------------------------------------------- publishing


def publish_library(
    conn: Any, *, library_key: str, published_by: str, reader: Optional[Any] = None
) -> dict:
    """Freeze the library's current documents as the next immutable version.

    Idempotent on the version digest (an unchanged corpus returns the existing
    row, no new version). Read-only against the external backend: this function
    never writes to Qdrant, never re-indexes, never touches ingest rules.
    """
    if not published_by:
        raise ValueError("published_by is required")
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")

    if reader is None:
        # The kernel never imports the backend layer (package-boundary gate). A
        # caller that wants the default must hand the reader in; the web/admin
        # surface does that with ``search.library_index``.
        raise ValueError(
            "publish_library requires a reader (see build_manifest); the web "
            "surface passes src.search.library_index"
        )
    manifest = build_manifest(conn, lib=lib, reader=reader)
    digest = version_digest(manifest["documents"])

    existing = conn.execute(
        f"SELECT {_PUBLICATION_COLS} FROM corpus_publications "
        "WHERE library_id = %s AND digest = %s",
        (lib["id"], digest),
    ).fetchone()
    if existing is not None:
        return _publication_to_dict(existing)

    max_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM corpus_publications WHERE library_id = %s",
        (lib["id"],),
    ).fetchone()
    latest = conn.execute(
        "SELECT manifest FROM corpus_publications WHERE library_id = %s "
        "ORDER BY version DESC LIMIT 1",
        (lib["id"],),
    ).fetchone()
    previous = _decode_jsonb(latest["manifest"]) if latest else None
    changelog = diff_manifests(previous, manifest)

    cur = conn.execute(
        f"INSERT INTO corpus_publications "
        f"(library_id, version, digest, shape_version, manifest, changelog, "
        f"doc_count, chunk_count, published_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_PUBLICATION_COLS}",
        (
            lib["id"],
            int(next(iter(max_version.values()))) + 1,
            digest,
            SHAPE_VERSION,
            json.dumps(manifest),
            json.dumps(changelog),
            manifest["total_docs"],
            manifest["total_chunks"],
            published_by,
        ),
    )
    publication = _publication_to_dict(cur.fetchone())
    conn.commit()
    return publication


def get_publication(
    conn: Any, *, library_key: str, version: Optional[int] = None
) -> Optional[dict]:
    """One published version of the library; ``version is None`` = the latest."""
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        return None
    sql = f"SELECT {_PUBLICATION_COLS} FROM corpus_publications WHERE library_id = %s"
    params: list[Any] = [lib["id"]]
    if version is not None:
        sql += " AND version = %s"
        params.append(version)
    sql += " ORDER BY version DESC LIMIT 1"
    row = conn.execute(sql, tuple(params)).fetchone()
    return _publication_to_dict(row) if row else None


def list_publications(conn: Any, *, library_key: str) -> list[dict]:
    """Every published version of the library, version ascending."""
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        return []
    cur = conn.execute(
        f"SELECT {_PUBLICATION_COLS} FROM corpus_publications "
        "WHERE library_id = %s ORDER BY version ASC",
        (lib["id"],),
    )
    return [_publication_to_dict(r) for r in cur.fetchall()]
