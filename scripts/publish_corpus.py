#!/usr/bin/env python3
"""Publish a corpus library — run in its OWN process, never inside the web pod.

## Why this is a script and not a request handler

Publication enumerates every document and fetches each body, which on the live
corpus is 32,251 round trips (~34 ms each). Measured inside the web pod
(2026-11-20):

    import the app + enumerate the documents   ~111 MB RSS
    container memory limit                      512 Mi
    what the serving process already holds      ~426 MB

So there is roughly 85 MB of headroom for a job that needs minutes and, in the
first (streaming) attempt, was **OOM-killed (exit 137)**. The binding constraint
is memory, not speed — which means publishing must not share the serving
process at all. `POST /admin/libraries/{key}/publish` therefore refuses and
points here.

## Usage

Inside the pod (a separate process with its own memory):

    kubectl -n law-bench exec <pod> -c law-bench -- \\
        sh -c 'cd /app && .venv/bin/python scripts/publish_corpus.py law-library --by <operator>'

Or as a one-off Job (see ``deploy/cheap-box/corpus-publish-job.yaml``), which is
the intended production path once it is scheduled.

Exit code 0 = published (or already published, idempotent); 1 = refused/failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library_key", help="library to publish (e.g. law-library)")
    parser.add_argument("--by", default="corpus-publish", help="operator stamp")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    sys.path.insert(0, os.getcwd())
    import packs.legal.asset_catalog  # noqa: F401 - registers asset kinds
    from src.bench import corpus_publication
    from src.eval.db import connect
    from src.search.library_index import LibraryCorpusReader

    conn = connect()
    reader = LibraryCorpusReader(conn)
    started = time.monotonic()
    try:
        publication = corpus_publication.publish_library(
            conn, library_key=args.library_key, published_by=args.by, reader=reader
        )
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    elapsed = round(time.monotonic() - started, 1)

    result = {
        "library": args.library_key,
        "version": publication["version"],
        "digest": publication["digest"],
        "shape_version": publication["shape_version"],
        "doc_count": publication["doc_count"],
        "chunk_count": publication["chunk_count"],
        "elapsed_seconds": elapsed,
        "changelog": "initial"
        if (publication.get("changelog") or {}).get("initial")
        else "diff",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"published {args.library_key} v{result['version']}")
        print(f"  digest  {result['digest']}")
        print(f"  docs    {result['doc_count']}  chunks {result['chunk_count']}")
        print(f"  took    {elapsed}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())