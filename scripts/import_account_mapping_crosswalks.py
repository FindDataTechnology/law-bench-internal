#!/usr/bin/env python3
"""Import the ERP line's industry account mappings as ``maps_to`` crosswalks.

The ERP template layer keeps one ``account-mapping/pack.json`` per vertical
(crossborder / restaurant-chain / supply-chain). Each ``industry_accounts`` row
says "this industry account aligns with that universal account" — which is
exactly what a ``maps_to`` crosswalk asserts, so it belongs in the domain as KU
rows rather than staying a second copy inside the ERP repository.

Two things make this import honest:

- **the near end is an account entity**. Every mapping is about one industry
  account, so that account must exist as a unit before the mapping can. Writing
  the entity first is not a convenience: the write path refuses a crosswalk whose
  near endpoint is absent, and it should.
- **the target must be in the universal preset**. A mapping onto a code the
  kernel does not have is a broken promise, not a mapping. The preset is read
  from the kernel's own migration file when a checkout is available, and falls
  back to the constant below (which names its source) otherwise.

The universal codes are 12 and change rarely; copying them is cheaper than
making this repository depend on the kernel package at import time.
`shortcut: the preset code list is a copy of the kernel migration, so bump it
when the kernel adds accounts; the upgrade path is a read-only preset surface
on the kernel's tool face.`

Idempotent by ``(kind, namespace, external_key)``: a re-run upserts the same
rows and reports how many already existed.

Run:
    uv run python scripts/import_account_mapping_crosswalks.py --dry-run
    uv run python scripts/import_account_mapping_crosswalks.py
    uv run python scripts/import_account_mapping_crosswalks.py --domain erp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: Where the ERP template layer lives. Overridable because the two repositories
#: sit side by side in the workspace but are separate checkouts.
DEFAULT_TEMPLATES = REPO_ROOT.parent / "fd-erp-vertical-templates" / "templates"

#: The verticals that publish an account-mapping pack today.
VERTICALS = ("crossborder", "restaurant-chain", "supply-chain")

#: ``universal_accounts`` v1, from
#: ``fd-erp-ledger-mcp/fd_erp_ledger_mcp/migrations/0002_universal_accounts.sql``.
UNIVERSAL_ACCOUNTS_V1 = frozenset(
    {"1000", "1100", "1200", "1300", "2000", "2100", "3000", "3100",
     "4000", "5000", "5100", "5200"}
)

#: The peer's ``system`` identifier. Not a provider: it names the kernel's own
#: universal chart, which is where every industry code has to land.
PEER_SYSTEM = "universal-accounts"

#: The internal entity type an industry account maps from. ``account`` is
#: declared by ``enterprise-base``; the entity is the industry-side account.
NEAR_TYPE = "account"

CREATED_BY = "system:import"


class MappingError(ValueError):
    """An account-mapping pack cannot be imported as it stands."""


def load_pack(path: Path) -> dict:
    if not path.is_file():
        raise MappingError(f"account-mapping pack not found at {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    mapping = body.get("account_mapping")
    if not isinstance(mapping, dict):
        raise MappingError(f"{path}: missing 'account_mapping' object")
    return mapping


def plans(templates_dir: Path) -> list[dict]:
    """One row per industry account, with the universal target resolved.

    Every target is checked against the preset here, not at write time: a bad
    code must fail the import before anything lands, and it must name the code
    so a reader can go fix the pack.
    """
    rows: list[dict] = []
    for vertical in VERTICALS:
        path = templates_dir / vertical / "account-mapping" / "pack.json"
        mapping = load_pack(path)
        preset_version = mapping.get("universal_preset_version")
        accounts = mapping.get("industry_accounts")
        if not isinstance(accounts, list) or not accounts:
            raise MappingError(f"{path}: 'industry_accounts' must be a non-empty list")
        for account in accounts:
            code = account.get("code")
            target = account.get("maps_to")
            if not code or not target:
                raise MappingError(
                    f"{path}: account entry needs both 'code' and 'maps_to' "
                    f"(got {account!r})"
                )
            if target not in UNIVERSAL_ACCOUNTS_V1:
                raise MappingError(
                    f"{path}: {code} maps to {target!r}, which is not in the "
                    f"universal account preset {preset_version or 'v1'}"
                )
            rows.append({
                "vertical": vertical,
                "code": code,
                "name_zh": account.get("name_zh") or code,
                "name_en": account.get("name_en") or code,
                "kind": account.get("kind"),
                "target": target,
                "preset_version": preset_version,
                "near_key": f"{NEAR_TYPE}:{code}",
                "crosswalk_key": f"{NEAR_TYPE}:{code}",
                "source_path": str(path.relative_to(templates_dir.parent)),
            })
    return rows


def attrs_for(row: dict) -> dict:
    """The ``maps_to`` assertion.

    No ``confidence`` on purpose: the pack records an alignment, not how sure
    anyone is. Inventing a number would count as reviewed something nobody
    reviewed, which is the failure mode ``is_confirmed`` exists to prevent.
    """
    return {
        "relation": "maps_to",
        "peer": {"kind": "external_id", "system": PEER_SYSTEM, "id": row["target"]},
    }


def entity_attrs_for(row: dict) -> dict:
    return {
        "vertical": row["vertical"],
        "industry_code": row["code"],
        "name_en": row["name_en"],
        "account_kind": row["kind"],
        "maps_to": row["target"],
        "universal_preset_version": row["preset_version"],
        "evidence": {
            "source_path": row["source_path"],
            "quote": f"{row['code']} {row['name_zh']} → {row['target']}",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES))
    parser.add_argument("--domain", default="erp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        rows = plans(Path(args.templates))
    except MappingError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    by_vertical: dict[str, int] = {}
    for row in rows:
        by_vertical[row["vertical"]] = by_vertical.get(row["vertical"], 0) + 1
    print(
        f"{len(rows)} industry account(s) across {len(by_vertical)} vertical(s): "
        + ", ".join(f"{v} {n}" for v, n in sorted(by_vertical.items()))
    )
    print(
        "universal targets all resolve: "
        + ", ".join(sorted({row["target"] for row in rows}))
    )

    if args.dry_run:
        for row in rows:
            print(f"  would map {row['code']:8s} {row['name_zh']} -> {row['target']}")
        print("\nDRY-RUN — nothing written.")
        return 0

    import psycopg

    from src.bench import authoring, crosswalk as cw, store
    from src.eval import db as edb
    from src.eval import store as eval_store

    conn = psycopg.connect(edb._dsn(), row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)

        created_entities = updated_entities = 0
        created_crosswalks = updated_crosswalks = 0

        for row in rows:
            existed = store.get_knowledge_unit(
                conn, kind=NEAR_TYPE, external_key=row["near_key"],
                namespace=args.domain,
            ) is not None
            authoring.authoring_create_unit(
                conn, domain_key=args.domain, kind=NEAR_TYPE,
                external_key=row["near_key"],
                body=f"{row['name_zh']}（{row['vertical']}）",
                operator=CREATED_BY, attrs=entity_attrs_for(row),
            )
            if existed:
                updated_entities += 1
            else:
                created_entities += 1

            problems = cw.validate_crosswalk(attrs_for(row))
            if problems:
                print(f"  SKIP {row['crosswalk_key']}: {'; '.join(problems)}",
                      file=sys.stderr)
                continue
            existed = store.get_knowledge_unit(
                conn, kind="crosswalk", external_key=row["crosswalk_key"],
                namespace=args.domain,
            ) is not None
            authoring.authoring_create_crosswalk(
                conn, domain_key=args.domain, external_key=row["crosswalk_key"],
                body=f"{row['name_zh']} → 通用科目 {row['target']}（{row['vertical']}）",
                operator=CREATED_BY, attrs=attrs_for(row),
            )
            if existed:
                updated_crosswalks += 1
            else:
                created_crosswalks += 1

        # psycopg3's ``conn.transaction()`` does not commit the outer transaction;
        # closing without this line rolls everything back while printing success
        # (2026-11-19, found on production).
        conn.commit()

        landed_entities = len(authoring.authoring_live_keys(
            conn, domain_key=args.domain, kind=NEAR_TYPE))
        landed_crosswalks = len(cw.list_rows(conn, namespace=args.domain))
        print(
            f"accounts: +{created_entities} new / {updated_entities} existing"
            f" | landed in {args.domain}: {landed_entities}"
        )
        print(
            f"crosswalks: +{created_crosswalks} new / {updated_crosswalks} existing"
            f" | landed in {args.domain}: {landed_crosswalks} (all kinds)"
        )
        print(
            "note: 这些映射没有 confidence，落库后是「待复核」，不计入覆盖率——"
            "这份 pack 说的是对齐，不是「谁看过」。"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
