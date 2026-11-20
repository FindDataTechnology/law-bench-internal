#!/usr/bin/env python3
"""Instantiate the finance domain from ``finance-market`` (idempotent).

    uv run python scripts/register_finance_domain.py --dry-run
    uv run python scripts/register_finance_domain.py

Why a domain and not just a template: the template (``finance-market`` v2) is a
*vocabulary*, and a vocabulary does not hold content. Until a domain exists,
nothing can be curated under those types, no proposal box exists, and the
domain cannot be published or pulled. The template row itself is never written
here — only reused.

The template declares no ``rubric_refs`` today, so the domain starts as a draft
(``template-readiness-gate``): that is legal and honest, and it is reported as
``quality:template`` until ``seed_finance_rubric.py`` plus the promotion step
give it rulers. Instantiation is deliberately not blocked on that — refusing
here would make the chicken-and-egg permanent, since a rubric belongs to a
domain and there is no domain yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import templates, workspaces  # noqa: E402

TEMPLATE_NAME = "finance-market"
DOMAIN_KEY = "finance"
DOMAIN_NAME = "金融数据域"
CREATED_BY = "system:register-finance"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=DOMAIN_KEY)
    parser.add_argument("--name", default=DOMAIN_NAME)
    parser.add_argument("--template", default=TEMPLATE_NAME)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        template = templates.get_template(conn, name=args.template)
        if template is None:
            print(
                f"template {args.template!r} not found — run "
                "scripts/register_layered_templates.py first",
                file=sys.stderr,
            )
            return 1

        schema = template["schema"] or {}
        print(
            f"template {args.template!r} v{template['version']} "
            f"(layer={schema.get('layer')}, "
            f"{len(schema.get('entity_types') or [])} entity types, "
            f"{len(schema.get('relationship_kinds') or [])} relationship kinds)"
        )

        existing = workspaces.get_domain(conn, domain_key=args.domain)
        if existing is not None:
            print(
                f"ALREADY REGISTERED — domain key {args.domain!r} exists "
                f"(id={existing['id']}, name={existing['name']!r}, template "
                f"{existing['template_name']!r} v{existing['template_version']}); "
                "no rows written."
            )
            return 0

        if args.dry_run:
            print(
                f"DRY-RUN plan: would instantiate domain key={args.domain!r} "
                f"name={args.name!r} anchored to {args.template!r} "
                f"v{template['version']}. Nothing written."
            )
            return 0

        created = workspaces.instantiate_domain(
            conn,
            key=args.domain,
            name=args.name,
            template_name=args.template,
            template_version=template["version"],
            created_by=CREATED_BY,
        )
        print(
            f"created domain {created['key']!r} (id={created['id']}) anchored to "
            f"{created['template_name']!r} v{created['template_version']}"
        )
        if not (schema.get("rubric_refs") or []):
            print(
                "note: the template declares no rulers, so this domain starts as a "
                "draft — the quality view reports it as quality:template until "
                "scripts/seed_finance_rubric.py runs and the template is promoted."
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
