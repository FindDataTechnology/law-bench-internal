#!/usr/bin/env python3
"""Shelve a domain's typed assets and publish them as a versioned snapshot.

    uv run python scripts/publish_domain_assets.py --domain finance --kind fact --dry-run
    uv run python scripts/publish_domain_assets.py --domain finance --kind fact

**Why this exists separately from ``publish_domain_snapshot.py``:** that script
publishes the *ontology* (entity + relationship units). Gold annotations are not
entities in the business vocabulary — putting ``fact`` into the template's
``entity_types`` would make every other type read as "unused" in the
declaration-vs-curation ledger, and would say the domain reasons about gold
annotations the way it reasons about instruments.

Typed asset publication is the right mechanism (change ``add-typed-publications``):
the domain #shelves the assets it stands behind, and the publication freezes that
shelf into a digest a consumer can pin.

Two steps, both idempotent:

1. **shelve** — assign every asset of ``kind`` the domain owns to its
   ``domain_assets`` directory. Only assets whose knowledge units live in this
   domain's namespace are shelved: a ruler that exists globally is not this
   domain's until someone puts it on the shelf.
2. **publish** — ``distribution.publish_asset_kind`` over that shelf.

A shelf that would be empty is refused before publishing: an empty snapshot is
not a snapshot of anything, and publishing one would hand a consumer a version
that pins nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PUBLISHED_BY = "system:publish-assets"


def _shelf_keys(conn, *, kind: str, domain_key: str) -> list[str]:
    """Which assets of ``kind`` this domain can stand behind.

    For ``fact`` the answer is content-derived: the knowledge units of that kind
    in the domain's namespace. For catalogued kinds (a ruler) it is the pack's
    own relation narrowed to what this domain actually references — but this
    script only auto-shelves kinds with a namespace-backed identity, because
    guessing which global rubrics belong to a domain is a judgement, not a read.
    """
    if kind != "fact":
        raise SystemExit(
            f"refusing to auto-shelve kind {kind!r}: only namespace-backed kinds "
            "can be derived. Assign other kinds by hand (they are a judgement "
            "about which global asset this domain stands behind)."
        )
    rows = conn.execute(
        "SELECT external_key FROM knowledge_units "
        "WHERE namespace = %s AND kind = %s AND (tags->>'deleted') IS NULL",
        (domain_key, kind),
    ).fetchall()
    return sorted(r["external_key"] for r in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    import importlib

    # Importing the pack is what registers its asset kinds with the kernel.
    importlib.import_module("packs.finance-data.asset_catalog")

    from src.bench import distribution, domain_assets, publication_kinds, workspaces
    from src.eval.db import connect

    registered = publication_kinds.list_kinds()
    if args.kind not in registered:
        print(
            f"kind {args.kind!r} is not registered for publication; "
            f"registered: {list(registered) or 'none (no pack provided one)'}",
            file=sys.stderr,
        )
        return 1

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"domain {args.domain!r} not found", file=sys.stderr)
            return 1

        keys = _shelf_keys(conn, kind=args.kind, domain_key=domain["key"])
        print(f"{args.domain}/{args.kind}: {len(keys)} asset(s) to shelve")
        if not keys:
            print("refusing an empty shelf — nothing to publish", file=sys.stderr)
            return 1

        if args.dry_run:
            for key in keys[:5]:
                print(f"  would shelve {key}")
            if len(keys) > 5:
                print(f"  ... {len(keys) - 5} more")
            print("DRY-RUN — nothing written.")
            return 0

        shelved = 0
        for key in keys:
            domain_assets.assign(
                conn, domain_key=domain["key"], asset_kind=args.kind,
                asset_key=key, added_by=PUBLISHED_BY,
            )
            shelved += 1
        conn.commit()
        print(f"shelved {shelved} asset(s)")

        published = distribution.publish_asset_kind(
            conn, domain_key=domain["key"], asset_kind=args.kind,
            published_by=PUBLISHED_BY,
        )
        # Read back rather than trust the return value.
        row = conn.execute(
            "SELECT version, digest FROM asset_publications "
            "WHERE domain_id = %s AND asset_kind = %s ORDER BY version DESC LIMIT 1",
            (domain["id"], args.kind),
        ).fetchone()
        if row is None or row["digest"] != published["digest"]:
            print(
                f"publication did not land (read back {row!r}, "
                f"returned {published['digest'][:8]})",
                file=sys.stderr,
            )
            return 1
        print(
            f"published {args.domain}/{args.kind} v{row['version']} "
            f"digest {row['digest'][:8]} (read back from the table)"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
