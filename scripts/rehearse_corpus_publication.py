#!/usr/bin/env python3
"""Add-corpus-publication §6.1/§6.2 rehearsal — run INSIDE the law-bench pod.

Why a script rather than ad-hoc shell: the rehearsal is the evidence for the
change's acceptance table, so it has to be re-runnable and its output pasteable.

What it does (read-only apart from the publication row it creates):

1. publish ``law-library`` once (records version, digest, doc/chunk counts,
   elapsed time) — §6.1;
2. page the manifest to the last page through the REAL HTTP surface, verifying
   no document is skipped or duplicated and ``next_cursor`` ends as ``null``;
3. sample three documents, fetch each body over HTTP, recompute its digest and
   compare with the manifest's ``doc_digest`` — §6.2.

Usage (inside the pod)::

    kubectl -n law-bench exec <pod> -c law-bench -- \\
        sh -c 'cd /app && .venv/bin/python scripts/rehearse_corpus_publication.py'

Exit code 0 = every assertion held; 1 = something disagreed (printed).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

LIBRARY_KEY = "law-library"
BASE_URL = os.environ.get("REHEARSAL_BASE_URL", "http://127.0.0.1:8010")
CONSUMER_NAME = "rehearsal-corpus-publication"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def _register_consumer(conn) -> tuple[str, int]:
    """A throwaway consumer bound to ``legal`` (which subscribes to the library)."""
    from src.bench import distribution

    token = "rehearsal-" + secrets.token_urlsafe(24)
    consumer = distribution.register_consumer(
        conn,
        name=CONSUMER_NAME,
        domains=["legal"],
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by="rehearsal",
    )
    return token, consumer["id"]


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(BASE_URL + path, headers={"X-Consumer-Token": token})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def main() -> int:
    sys.path.insert(0, os.getcwd())
    import packs.legal.asset_catalog  # noqa: F401 - registers kinds/providers
    from src.bench import corpus_publication
    from src.eval.db import connect
    from src.search.library_index import LibraryCorpusReader

    conn = connect()

    # ---------------------------------------------------------------- §6.1
    started = time.monotonic()
    # Publishing the live corpus takes ~18 min (one round trip per document);
    # this script is meant to run in its own process for exactly that reason.
    publication = corpus_publication.publish_library(
        conn, library_key=LIBRARY_KEY, published_by="rehearsal",
        reader=LibraryCorpusReader(conn, max_seconds=7200.0, max_pages=8000),
    )
    elapsed = time.monotonic() - started
    print("§6.1 publish")
    print(json.dumps({
        "library": LIBRARY_KEY,
        "version": publication["version"],
        "digest": publication["digest"],
        "shape_version": publication["shape_version"],
        "doc_count": publication["doc_count"],
        "chunk_count": publication["chunk_count"],
        "elapsed_seconds": round(elapsed, 1),
        "changelog_kind": "initial" if publication["changelog"].get("initial") else "diff",
    }, ensure_ascii=False, indent=2))

    token, consumer_id = _register_consumer(conn)
    try:
        # ------------------------------------------------------------ §6.2a
        seen: list[str] = []
        cursor = None
        pages = 0
        while True:
            query = f"?limit=1000" + (f"&cursor={cursor}" if cursor else "")
            page = _get(
                f"/api/v1/distribution/libraries/{LIBRARY_KEY}/corpus{query}", token
            )
            pages += 1
            if page["digest"] != publication["digest"]:
                _fail(f"page {pages} digest {page['digest']} != published {publication['digest']}")
            seen.extend(d["doc_key"] for d in page["documents"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        print("\n§6.2 manifest paging")
        print(json.dumps({
            "pages": pages,
            "documents_seen": len(seen),
            "unique_documents": len(set(seen)),
            "published_doc_count": publication["doc_count"],
            "duplicates": len(seen) - len(set(seen)),
        }, ensure_ascii=False, indent=2))
        if len(seen) != len(set(seen)):
            _fail("the manifest paging returned a document twice")
        if len(set(seen)) != publication["doc_count"]:
            _fail(
                f"paged {len(set(seen))} documents but the publication says "
                f"{publication['doc_count']}"
            )

        # ------------------------------------------------------------ §6.2b
        manifest = {d["doc_key"]: d for d in publication["manifest"]["documents"]}
        # Three documents spread across the corpus, not just the first three.
        ordered = sorted(manifest)
        sample = [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
        print("\n§6.2 sample documents")
        for doc_key in sample:
            body = _get(
                f"/api/v1/distribution/libraries/{LIBRARY_KEY}/corpus/{doc_key}", token
            )
            recomputed = corpus_publication.doc_digest(body["title"], body["body"])
            ok = (
                recomputed == body["doc_digest"]
                and body["doc_digest"] == manifest[doc_key]["doc_digest"]
                and body["body_matches"] is True
            )
            print(json.dumps({
                "doc_key": doc_key,
                "title": body["title"],
                "chunk_count": body["chunk_count"],
                "body_chars": len(body["body"]),
                "digest_matches_manifest": body["doc_digest"] == manifest[doc_key]["doc_digest"],
                "recomputed_matches": recomputed == body["doc_digest"],
                "body_matches_flag": body["body_matches"],
                "ok": ok,
            }, ensure_ascii=False))
            if not ok:
                _fail(f"document {doc_key!r} did not verify")

        # Footprints: one row per successful pull, none for the failures above.
        rows = conn.execute(
            "SELECT count(*) AS n FROM corpus_pull_events WHERE consumer_id = %s",
            (consumer_id,),
        ).fetchone()
        print("\n§4.4 footprints for this consumer:", rows["n"])
        if rows["n"] != pages + len(sample):
            _fail(
                f"expected {pages + len(sample)} footprints (pages + documents), got {rows['n']}"
            )
    finally:
        from src.bench import distribution

        distribution.revoke_consumer(conn, name=CONSUMER_NAME)

    print("\nREHEARSAL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())