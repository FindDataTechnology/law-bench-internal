"""Publish a domain's current content as the next immutable snapshot.

    uv run python scripts/publish_domain_snapshot.py --domain erp --dry-run
    uv run python scripts/publish_domain_snapshot.py --domain erp --domain finance

Thin wrapper over ``distribution.publish_domain`` — that function owns the
digest, the immutability and the changelog; this file only adds the two things a
script needs: ``--dry-run`` (report what would be frozen without freezing it)
and a read-back that proves the row landed rather than trusting the return value.

The read-back matters here specifically: a publication that silently rolled back
would still print a version number, and the consumer-side pull would then have
nothing to fetch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PUBLISHED_BY = "system:publish-script"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", action="append", required=True,
                        help="domain key; repeat for several")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from src.bench import distribution, workspaces
    from src.eval.db import connect

    conn = connect()
    try:
        failures = 0
        for key in args.domain:
            domain = workspaces.get_domain(conn, domain_key=key)
            if domain is None:
                print(f"{key}: domain not found", file=sys.stderr)
                failures += 1
                continue
            try:
                manifest, entities, relationships = distribution.build_manifest(
                    conn, domain=domain
                )
            except ValueError as exc:
                print(f"{key}: cannot publish — {exc}", file=sys.stderr)
                failures += 1
                continue
            digest = distribution.canonical_digest(manifest)
            print(
                f"{key}: {entities} entities / {relationships} relationships, "
                f"digest {digest[:8]}"
            )
            if entities == 0 and relationships == 0:
                print(f"{key}: refusing an empty snapshot", file=sys.stderr)
                failures += 1
                continue
            if args.dry_run:
                continue

            published = distribution.publish_domain(
                conn, domain_key=key, published_by=PUBLISHED_BY
            )
            # Read back rather than trust the return value.
            row = conn.execute(
                "SELECT version, digest FROM ontology_publications "
                "WHERE domain_id = %s ORDER BY version DESC LIMIT 1",
                (domain["id"],),
            ).fetchone()
            if row is None or row["digest"] != published["digest"]:
                print(
                    f"{key}: publication did not land (read back {row!r}, "
                    f"returned {published['digest'][:8]})",
                    file=sys.stderr,
                )
                failures += 1
                continue
            print(
                f"{key}: published v{row['version']} digest {row['digest'][:8]} "
                "(read back from the table)"
            )

        if args.dry_run:
            print("\nDRY-RUN — nothing written.")
        return 1 if failures else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
