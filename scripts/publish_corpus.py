#!/usr/bin/env python3
"""Publish a corpus library — in its OWN POD, never inside the app container.

## Why this is a script and not a request handler

Publication enumerates every document and fetches each body: 32,251 round trips
on the live corpus, and ~109 MB RSS just to import the app and enumerate. The
app container is capped at 512 Mi and already holds 426–470 MB while serving.

**Two measured OOMKills (exit 137) proved the boundaries**, in order:

1. inline in the request path — shares the serving process, dies;
2. ``kubectl exec`` into the app pod — **also dies**, because an exec'd process
   shares that container's cgroup, so the 512 Mi ceiling still applies. This one
   ran ~55 minutes before being killed.

So "a separate process" is NOT the fix; "a separate Pod" is. Run it as
``fd-infra-deploy/all-services/law-bench/jobs/corpus-publish-job.yaml``, which
gives the publisher its own memory limit. `POST /admin/libraries/{key}/publish`
refuses (409) and points here.

## Usage

    kubectl -n law-bench apply -f \\
        fd-infra-deploy/all-services/law-bench/jobs/corpus-publish-job.yaml

Direct invocation is fine for small libraries or tests — just do not point it at
a full corpus inside a 512 Mi container.


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

    # Progress on stderr, every N documents. Publishing takes ~20 minutes and
    # the first run gave the operator no way to tell "working" from "hung" —
    # system-call counters and bytes-read turned out to be unusable proxies
    # (module imports dominate early, so byte counts grossly overstate progress).
    # A counted line is the only honest signal.
    total_docs_holder = {"n": 0}

    class _ProgressingReader:
        def iter_documents(self, *, lib):
            for doc in reader.iter_documents(lib=lib):
                total_docs_holder["n"] += 1
                n = total_docs_holder["n"]
                if n % 500 == 0:
                    rate = n / max(time.monotonic() - started, 1e-6)
                    print(
                        f"  ... {n} documents ({rate:.0f}/s, "
                        f"{time.monotonic() - started:.0f}s elapsed)",
                        file=sys.stderr, flush=True,
                    )
                yield doc

    try:
        publication = corpus_publication.publish_library(
            conn, library_key=args.library_key, published_by=args.by,
            reader=_ProgressingReader(),
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
