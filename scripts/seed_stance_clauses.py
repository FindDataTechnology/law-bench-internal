#!/usr/bin/env python3
"""Load per-type seed manifests into the ``clauses`` table.

Thin wrapper over :func:`src.clauses.seed_manifest.load_one` / :func:`load_all`.
For each manifest under ``data/clause_seeds/<type>.yaml``: delete existing seed
clauses for the type (``source_doc_title = 'seed:<type>'``), then
:func:`create_clause` each (``category=custom``, ``manual=true``, ``tags`` from
``stance``/``strength``, ``slot_instructions`` from the manifest). Idempotent.

Usage::

    uv run python scripts/seed_stance_clauses.py                 # all manifests
    uv run python scripts/seed_stance_clauses.py --type employment  # one type
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.seed_manifest import load_all, load_one, seed_tag_dims  # noqa: E402
from src.clauses.tags import load_vocab_from_db  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Load per-type seed clause manifests into Postgres.")
    parser.add_argument("--type", help="load only this contract_type")
    args = parser.parse_args()
    ensure_schema()
    n_dims = seed_tag_dims()  # upsert the tag vocabulary into tag_dims
    load_vocab_from_db()  # populate the in-memory TAG_VOCAB from tag_dims
    if args.type:
        counts = {args.type: load_one(args.type)}
    else:
        counts = load_all()
    for t, n in counts.items():
        print(f"  {t}: {n} clauses")
    print(f"loaded {sum(counts.values())} clauses across {len(counts)} types; {n_dims} tag dims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
