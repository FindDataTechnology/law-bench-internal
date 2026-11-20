#!/usr/bin/env python3
"""Give an industry template rulers and re-anchor its domain (idempotent).

    uv run python scripts/promote_industry_template.py --template finance-market \
        --domain finance --rubric finance-fact-quality --dry-run
    uv run python scripts/promote_industry_template.py --template finance-market \
        --domain finance --rubric finance-fact-quality

Why this exists as one script for two templates: the step is identical, and two
copies would let the two lines drift in exactly the place that decides whether a
domain can ever be measured.

The three steps and why each must be in this order:

1. the rubric must already exist **in the domain** (``seed_*_rubric.py``) —
   ``instantiate_domain`` refuses a template whose declared rulers cannot
   resolve, so declaring first would make the template uninstantiable;
2. the new template version declares ``rubric_refs`` and goes through
   ``promote_template_via_gate`` — the gate is what stops "delete the rulers,
   ship a worse version". A first promotion with rulers establishes the baseline;
3. only then is the domain moved onto the new version.

``--reanchor`` is required to move a live domain, same discipline as
``publish_gov_template_v2.py``: moving a production anchor is deliberate and
prints its rollback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import template_readiness, templates, workspaces  # noqa: E402


def with_rubrics(schema: dict, rubric: str) -> dict:
    schema = json.loads(json.dumps(schema))  # deep copy, JSON-safe
    refs = [r for r in (schema.get("rubric_refs") or []) if isinstance(r, str)]
    if rubric not in refs:
        refs.append(rubric)
    schema["rubric_refs"] = sorted(set(refs))
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--rubric", required=True,
                        help="rubric name that must already be visible in the domain")
    parser.add_argument("--reanchor", action="store_true",
                        help="ALSO move the domain onto the new version (deliberate)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from src.bench import domain_rubrics
    from src.eval.db import connect

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"domain {args.domain!r} not found", file=sys.stderr)
            return 1
        path = domain.get("path") or domain["key"]

        # Step 0: the ruler must already resolve in this domain, or the new
        # template version declares a ruler the domain cannot use.
        available = {r["name"] for r in
                     domain_rubrics.effective_rubrics(conn, domain_path=path)}
        if args.rubric not in available:
            print(
                f"rubric {args.rubric!r} is not visible in domain {args.domain!r}; "
                f"run the matching seed_*_rubric.py first. Visible: {sorted(available)}",
                file=sys.stderr,
            )
            return 1

        latest = templates.get_template(conn, name=args.template)
        if latest is None:
            print(f"template {args.template!r} not found", file=sys.stderr)
            return 1

        declared = template_readiness.rubric_refs(latest["schema"] or {})
        if args.rubric in declared:
            print(
                f"template {args.template!r} v{latest['version']} already declares "
                f"{args.rubric!r}; nothing to promote."
            )
            return 0

        schema = with_rubrics(latest["schema"] or {}, args.rubric)
        print(f"v{latest['version']} rubric_refs: {declared or '[]'}")
        print(f"new rubric_refs       : {schema['rubric_refs']}")
        print(f"readiness now: {template_readiness.readiness(conn, domain_path=path, schema=latest['schema'] or {})}")

        if args.dry_run:
            print("[dry-run] would create the next template version; nothing written")
            return 0

        created = template_readiness.promote_template_via_gate(
            conn, name=args.template, schema=schema,
            created_by="promote_industry_template",
        )
        print(
            f"published template {args.template!r} v{created['version']} "
            f"(id={created['id']}) with rulers {schema['rubric_refs']}"
        )

        if not args.reanchor:
            print(
                f"domain {args.domain!r} is still anchored to v{domain['template_version']} "
                "(pass --reanchor to move it on purpose)"
            )
            return 0

        before = domain["template_version"]
        conn.execute(
            "UPDATE domains SET template_id = %s, template_version = %s WHERE id = %s",
            (created["id"], created["version"], domain["id"]),
        )
        conn.commit()
        print(f"re-anchored domain {args.domain!r}: v{before} -> v{created['version']}")
        print(
            f"rollback: domains.template_id={latest['id']}, "
            f"template_version={latest['version']}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
