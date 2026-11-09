"""Register the real corpora as shared libraries (idempotent, admin one-off).

Run inside the law-bench pod after a rollout::

    python3 scripts/register_libraries.py            # apply
    python3 scripts/register_libraries.py --dry-run  # print the plan only

Why a script instead of console UI: creating a *library* is platform-level, not
domain-level work (a library exists before any domain subscribes), and the first
ones are migrations of corpora that already exist elsewhere. An admin form can
come later; what matters now is that the registration is idempotent and that
every number it writes is measured, not assumed.

``text-library`` registers the text engine's four verticals read-only and
**without any subscription** — that corpus belongs to another product line.

``law-library`` sources partition the Qdrant collection **exhaustively** — every
one of the 364,916 points belongs to exactly one source, so "which source" is
never a guess and no chunk is silently unreachable::

    statutes        法律 / 宪法 / 法律解释 / 有关法律问题和重大问题的决定*
    administrative  行政法规 / 法规性决定 / 监察法规
    judicial        司法解释
    local           地方性法规 / 地方法规          ← same class, two spellings
    departmental    规章
    amendment       修改、废止的决定
    unclassified    重下载 / 新法速递 / 规范性文件  (crawl artifacts, kept honest)

Counts were measured with Qdrant's facet API on 2026-11-08; the script re-counts
after writing and fails if the sources do not add up to the collection size.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ is not a package: make the repo root importable so ``src.*`` resolves
# whether this runs from the repo or inside the image (``/app``).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bench import libraries  # noqa: E402

#: (source_key, human label, payload values). The values are matched with
#: Qdrant's `any`, so a source can cover several spellings of one class.
LAW_SOURCES: list[tuple[str, str, list[str]]] = [
    # The last value is truncated *in the corpus itself* (20-char column), not
    # in this file — quoting the untruncated name would silently drop 29 points.
    ("statutes", "法律/宪法",
     ["法律", "宪法", "法律解释", "有关法律问题和重大问题的决定（部"]),
    ("administrative", "行政法规", ["行政法规", "法规性决定", "监察法规"]),
    ("judicial", "司法解释", ["司法解释"]),
    ("local", "地方性法规", ["地方性法规", "地方法规"]),
    ("departmental", "部门规章", ["规章"]),
    ("amendment", "修改、废止的决定", ["修改、废止的决定"]),
    ("unclassified", "待归类（爬取产物）", ["重下载", "新法速递", "规范性文件"]),
]


def register_law_library(conn, *, domain_key: str = "legal", dry_run: bool = False) -> dict:
    from src.search import library_index

    existing = libraries.get_library(conn, library_key="law-library")
    if existing is None:
        if dry_run:
            # Nothing is written, so there is no row to read the sources from —
            # report the plan and stop. (Reading it back here was the first
            # draft's TypeError: dry-run must not depend on its own writes.)
            print("  would create library law-library (qdrant, 1024, Qwen3-Embedding-0.6B)")
            for key, label, values in LAW_SOURCES:
                print(f"  would add source {key:15s} {label} -> {values}")
            print(f"  would subscribe {domain_key} to every source of law-library")
            return {"library": "law-library", "sources": len(LAW_SOURCES), "dry_run": True}
        libraries.create_library(
            conn,
            library_key="law-library",
            name="法规大库",
            created_by="register_libraries",
            backend="qdrant",
            embedding_model="Qwen/Qwen3-Embedding-0.6B",
            dims=1024,
            location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"},
        )
        existing = libraries.get_library(conn, library_key="law-library")

    have = {s["source_key"] for s in libraries.list_sources(conn, library_id=existing["id"])}
    for key, label, values in LAW_SOURCES:
        if key in have:
            print(f"  source {key:15s} exists")
            continue
        if dry_run:
            print(f"  would add source {key:15s} {label} -> {values}")
            continue
        libraries.add_source(
            conn,
            library_key="law-library",
            source_key=key,
            uri=f"collection:law_chunks_v2#{key}",
            created_by="register_libraries",
            source_kind="payload-filter",
            ingest_rule={"match": {"category": values}},
            content_type=f"法规/{label}",
        )
        print(f"  source {key:15s} added")

    domain = conn.execute("SELECT id, path FROM domains WHERE key=%s", (domain_key,)).fetchone()
    if domain is None:
        raise SystemExit(f"domain {domain_key!r} not found — create it before subscribing")
    if dry_run:
        print(f"  would subscribe {domain_key} to every source of law-library")
        return {"library": "law-library", "sources": len(LAW_SOURCES), "dry_run": True}

    libraries.subscribe(
        conn, domain_id=domain["id"], library_key="law-library",
        created_by="register_libraries", source_filter=None,
    )

    # Verify rather than trust: the sources must partition the collection.
    total = library_index._count_qdrant(
        conn, lib=libraries.get_library(conn, library_key="law-library"), allowed=set()
    )
    per_source = {}
    for key, _label, _values in LAW_SOURCES:
        per_source[key] = library_index._count_qdrant(
            conn, lib=libraries.get_library(conn, library_key="law-library"), allowed={key}
        )
    covered = sum(per_source.values())
    print(f"  domain {domain_key} subscribed to all {len(LAW_SOURCES)} sources")
    for key, n in per_source.items():
        print(f"    {key:15s} {n:8d}")
    print(f"    {'TOTAL':15s} {covered:8d}  (library unfiltered {total})")
    if covered != total:
        # Not fatal for the subscription (it is already live), but the taxonomy
        # is wrong and the next reader must know: an uncovered chunk is a chunk
        # nobody can retrieve.
        print(f"  !! sources cover {covered} of {total} points — unclassified gap",
              file=sys.stderr)
        return {"library": "law-library", "total": total, "covered": covered, "ok": False}
    return {"library": "law-library", "total": total, "covered": covered, "ok": True}


#: The text engine's four verticals. One table per vertical, so a source *is* a
#: table here — the generic "prefix" idea does not apply. Counts measured
#: 2026-11-08: gov 2,160 / news 2,942 / papers 82 / screenplay 2,305.
#:
#: This library is registered **without any subscription** on purpose: the
#: content is another product line's corpus (政务/新闻/论文/剧本), not statutes.
#: Registering it makes it selectable in the ledger; nobody's retrieval changes
#: until a domain deliberately subscribes. Searching it additionally needs
#: ``LIBRARY_EMBED_GATEWAY_KEY`` (8B model); without it the search fails loudly
#: instead of silently degrading.
TEXT_SOURCES: list[tuple[str, str, str]] = [
    ("gov", "政务公开文本", "corpus_chunks_gov"),
    ("news", "新闻文本", "corpus_chunks_news"),
    ("papers", "论文文本", "corpus_chunks_papers"),
    ("screenplay", "剧本文本", "corpus_chunks_screenplay"),
]


def register_text_library(conn, *, dry_run: bool = False) -> dict:
    """Register the text engine's verticals as an unsubscribed library."""
    lib = libraries.get_library(conn, library_key="text-library")
    if lib is None:
        if dry_run:
            print("  would create library text-library (pgvector-external, 1024, "
                  "Qwen/Qwen3-Embedding-8B)")
            for key, label, table in TEXT_SOURCES:
                print(f"  would add source {key:11s} {label} -> {table}")
            return {"library": "text-library", "sources": len(TEXT_SOURCES), "dry_run": True}
        libraries.create_library(
            conn,
            library_key="text-library",
            name="文字垂域库（政务/新闻/论文/剧本）",
            created_by="register_libraries",
            backend="pgvector-external",
            embedding_model="Qwen/Qwen3-Embedding-8B",
            dims=1024,
            location={"dsn_env": "FDTEXT_DATABASE_URL"},
        )
        lib = libraries.get_library(conn, library_key="text-library")

    have = {s["source_key"] for s in libraries.list_sources(conn, library_id=lib["id"])}
    for key, label, table in TEXT_SOURCES:
        if key in have:
            print(f"  source {key:11s} exists")
            continue
        if dry_run:
            print(f"  would add source {key:11s} {label} -> {table}")
            continue
        libraries.add_source(
            conn,
            library_key="text-library",
            source_key=key,
            uri=table,
            created_by="register_libraries",
            source_kind="external-table",
            content_type=f"文本/{label}",
        )
        print(f"  source {key:11s} added")

    if dry_run:
        print("  no subscription written (by design: another product line's corpus)")
        return {"library": "text-library", "sources": len(TEXT_SOURCES), "dry_run": True}

    # Report per-table counts so the ledger is not a promise with no numbers.
    from src.search import library_index

    counts = {}
    try:
        counts = library_index.source_counts(
            conn, lib=libraries.get_library(conn, library_key="text-library"),
            allowed={s["source_key"] for s in TEXT_SOURCES},
        )
    except Exception as exc:  # unreachable DSN must not read as "empty"
        print(f"  !! counts unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    for key, n in counts.items():
        print(f"    {key:11s} {n:8d}")
    subscribed = conn.execute(
        "SELECT COUNT(*) AS n FROM domain_library_subscriptions s "
        "JOIN libraries l ON l.id = s.library_id WHERE l.library_key = 'text-library'"
    ).fetchone()["n"]
    print(f"  subscribers: {subscribed} (expected 0)")
    return {"library": "text-library", "counts": counts, "subscribers": subscribed,
            "ok": subscribed == 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="legal")
    ap.add_argument("--only", choices=("law", "text", "all"), default="all",
                    help="which library to register (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    ok = True
    try:
        if args.only in ("law", "all"):
            out = register_law_library(conn, domain_key=args.domain, dry_run=args.dry_run)
            print(out)
            ok = ok and bool(out.get("ok", True))
        if args.only in ("text", "all"):
            out = register_text_library(conn, dry_run=args.dry_run)
            print(out)
            ok = ok and bool(out.get("ok", True))
    finally:
        conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
