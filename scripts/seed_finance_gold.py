#!/usr/bin/env python3
"""Land the sentiment gold set inside the finance domain (idempotent).

    uv run python scripts/seed_finance_gold.py --dry-run
    uv run python scripts/seed_finance_gold.py

The gold records themselves live in ``packs/finance-data``, which reads them at
runtime from the sibling ``fd-sentiment`` checkout — no data file is copied into
this repository, and that stays true here: this script only re-lands what the
pack already parses, under the domain's namespace.

**Why not just call the pack's ``load_sentiment_gold``:** it writes to
``namespace='finance-data'``, which is a pack namespace, not a domain. Knowledge
units are scoped by namespace = the domain key, so gold landed there would be
invisible to the finance domain's quality view, its ledger, and its publication
manifest — the domain would look empty while 105 gold rows sat one namespace
over.

**Why not the authoring write path:** it hardcodes ``tier="raw"``, and these are
human-annotated gold. The pack itself writes through ``upsert_knowledge_unit``
for that reason; this script uses the same store-level write and carries the
same provenance block.

A missing sibling checkout raises instead of writing nothing quietly: an empty
gold set and an unreadable one are different facts, and only one of them is
worth reporting as "0 rows".
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CREATED_BY = "system:import"


def _adapters():
    """Import the pack's adapter module (its directory name has a dash)."""
    return importlib.import_module("packs.finance-data.adapters")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="finance")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from src.bench import store, workspaces

    adapters = _adapters()

    try:
        records = adapters.read_gold_records()
    except Exception as exc:  # noqa: BLE001 — the message is the report
        print(
            f"REFUSED: cannot read the gold set ({type(exc).__name__}: {exc}). "
            "No rows written — an empty gold set and an unreadable one are "
            "different facts.",
            file=sys.stderr,
        )
        return 1

    print(
        f"gold records: {len(records)} "
        f"(set {records[0].get('set_version')} from {adapters.GOLD_REL})"
    )

    if args.dry_run:
        for record in records[:3]:
            print(
                f"  {record['doc_id']}  {record['as_of']}  "
                f"{record['expected_band']}"
            )
        print(f"  ... {len(records) - 3} more" if len(records) > 3 else "")
        print("\nDRY-RUN — nothing written.")
        return 0

    from src.eval.db import connect

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"domain {args.domain!r} not found", file=sys.stderr)
            return 1

        created = updated = 0
        for record in records:
            unit = adapters.record_to_unit(record)
            # Namespace is the domain's, not the pack's: the same gold rows, in
            # the scope that can actually see and publish them.
            unit["namespace"] = domain["key"]
            existed = store.get_knowledge_unit(
                conn, kind=unit["kind"], external_key=unit["external_key"],
                namespace=domain["key"],
            ) is not None
            store.upsert_knowledge_unit(conn, commit=False, **unit)
            if existed:
                updated += 1
            else:
                created += 1
        conn.commit()

        landed = conn.execute(
            "SELECT count(*) AS n FROM knowledge_units "
            "WHERE namespace = %s AND kind = %s AND tier = 'gold' "
            "  AND (tags->>'deleted') IS NULL",
            (domain["key"], adapters.KIND),
        ).fetchone()["n"]
        print(
            f"gold units: +{created} new / {updated} existing "
            f"| landed in {args.domain}: {landed}"
        )
        if landed != len(records):
            print(
                f"WARNING: landed {landed} but read {len(records)} — the two "
                "should match; investigate before publishing.",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
