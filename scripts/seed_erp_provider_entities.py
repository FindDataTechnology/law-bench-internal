#!/usr/bin/env python3
"""Seed the ERP domain's own entities for the external systems it maps to.

The ERP template layer keeps ``connector-status.json`` — the derived three-state
evidence for each integration (catalog / executor_tests / live). The platform is
the read authority for that evidence, so the crosswalk rows were imported long
ago. What was never seeded is the **near end**: those crosswalks assert
``organization:<provider> --same_as--> <provider>`` and no ``organization:kingdee``
ever existed, so production carried 8 dangling mappings (measured 2026-11-21).

The quality view reported them as "external system not connected", which points
whoever reads it at an integration that was never the problem.

This script seeds only what the file already attests to — one entity per external
system, with its name, its owning vertical and its binding keys. It invents
nothing: a system absent from ``connector-status.json`` gets no entity.

Idempotent by ``(kind, namespace, external_key)``.

Run:
    uv run python scripts/seed_erp_provider_entities.py --dry-run
    uv run python scripts/seed_erp_provider_entities.py
    uv run python scripts/seed_erp_provider_entities.py --domain erp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_STATUS = (
    REPO_ROOT.parent / "fd-erp-vertical-templates" / "connector-status.json"
)

#: The entity type an external system lands on in ``enterprise-base``.
NEAR_TYPE = "organization"

CREATED_BY = "system:import"


class StatusError(ValueError):
    """connector-status.json cannot be read as a provider list."""


def load_status(path: Path) -> dict:
    if not path.is_file():
        raise StatusError(f"connector-status.json not found at {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("integrations"), list):
        raise StatusError(f"{path}: expected an 'integrations' list")
    return body


def plans(status: dict) -> list[dict]:
    """One entity per distinct provider.

    ``wechatpay`` appears under two verticals (restaurant-chain and supply-chain)
    with different external systems and different binding keys. One entity, both
    verticals recorded: the same payment channel is not two organizations.
    """
    by_provider: dict[str, dict] = {}
    for row in status["integrations"]:
        provider = row.get("provider")
        if not provider:
            raise StatusError(f"integration without a provider: {row!r}")
        entry = by_provider.setdefault(provider, {
            "provider": provider,
            "external_systems": [],
            "verticals": [],
            "binding_keys": [],
            "states": {},
        })
        for field, bucket in (
            ("external_system", "external_systems"),
            ("template", "verticals"),
        ):
            value = row.get(field)
            if value and value not in entry[bucket]:
                entry[bucket].append(value)
        for key in row.get("binding_keys") or []:
            if key not in entry["binding_keys"]:
                entry["binding_keys"].append(key)
        entry["states"].update(row.get("states") or {})
    return [by_provider[p] for p in sorted(by_provider)]


def attrs_for(entry: dict) -> dict:
    return {
        "external_system": " / ".join(entry["external_systems"]),
        "verticals": list(entry["verticals"]),
        "binding_keys": list(entry["binding_keys"]),
        # Verbatim from connector-status.json — this script records the evidence
        # the ERP line already derived, it does not re-derive or upgrade it.
        "connector_states": entry["states"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default=str(DEFAULT_STATUS))
    parser.add_argument("--domain", default="erp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = plans(load_status(Path(args.status)))
    except StatusError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(f"{len(entries)} external system(s):")
    for entry in entries:
        complete = sum(
            1 for state in ("catalog", "executor_tests", "live")
            if (entry["states"].get(state) or {}).get("ok")
        )
        print(
            f"  {entry['provider']:16s} "
            f"({'/'.join(entry['verticals'])}): {complete}/3 states ok"
        )

    if args.dry_run:
        print("\nDRY-RUN — nothing written.")
        return 0

    import psycopg

    from src.bench import authoring, store
    from src.eval import db as edb
    from src.eval import store as eval_store

    conn = psycopg.connect(edb._dsn(), row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)

        created = updated = 0
        for entry in entries:
            key = f"{NEAR_TYPE}:{entry['provider']}"
            existed = store.get_knowledge_unit(
                conn, kind=NEAR_TYPE, external_key=key, namespace=args.domain,
            ) is not None
            authoring.authoring_create_unit(
                conn, domain_key=args.domain, kind=NEAR_TYPE, external_key=key,
                body=entry["external_systems"][0],
                operator=CREATED_BY, attrs=attrs_for(entry),
            )
            if existed:
                updated += 1
            else:
                created += 1

        # psycopg3's ``conn.transaction()`` does not commit the outer transaction;
        # closing without this rolls everything back while printing success.
        conn.commit()

        landed = authoring.authoring_live_keys(
            conn, domain_key=args.domain, kind=NEAR_TYPE
        )
        provider_keys = {f"{NEAR_TYPE}:{e['provider']}" for e in entries}
        print(
            f"entities: +{created} new / {updated} existing"
            f" | landed in {args.domain}: {len(landed)} of kind {NEAR_TYPE}"
            f" | providers present: {len(provider_keys & landed)}/{len(provider_keys)}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
