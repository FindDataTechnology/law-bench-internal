#!/usr/bin/env python3
"""Land the fd-cn-gov registry as ``gov-fact`` units in the gov domain (idempotent).

    uv run python scripts/load_gov_registry.py --dry-run
    uv run python scripts/load_gov_registry.py
    FD_GOV_REPO=/path/to/fd-cn-gov uv run python scripts/load_gov_registry.py
    uv run python scripts/load_gov_registry.py --load-only      # skip the data eval
    uv run python scripts/load_gov_registry.py --no-eval

The registry is the 公文爬虫 registry (sources / datasource_columns /
scraw_configs / organizations) that lives in the sibling ``fd-cn-gov`` checkout
under ``fd_cn_gov/registry/registry.json``. The pack's adapter already maps it to
``gov-fact`` units in ``namespace='gov'`` (the domain key — no namespace
mismatch like finance's pack had); this script only:

1. re-lands those units (idempotent upsert on ``(kind, namespace, source_name)``),
   overriding ``FD_GOV_REPO`` when ``--repo`` is given so it can run against a
   copy of the registry instead of a full sibling checkout, and
2. runs one deterministic data evaluation over the gov domain so the freshly
   landed units get scored immediately and the domain's ``last_run`` moves.

Why a script and not the authoring path: the units are machine-derived from an
official registry (``tier='silver'``), and the pack writes through
``upsert_knowledge_unit`` for exactly that reason — this reuses the pack's own
loader so a re-run after the registry changes updates in place and lands no
duplicates.

Honest scope: the registry is the *source catalogue* (which agency archives feed
crawls, with which column schema) — NOT 公文正文. These 11 ``gov-fact`` units sit
beside the existing ``document``/``agency`` ontology; they are a different kind,
so they neither pollute nor replace it. On clean data every deterministic checker
passes 11/11 — that is the correct outcome, and the checkers exist as an alarm
for a future corrupt registry, not to find faults in today's.

A missing registry raises instead of writing nothing quietly: "registry is empty"
and "registry could not be read" are different facts.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CREATE_BY = "system:load-gov-registry"


def _set_repo(repo: str | None) -> None:
    """Point the pack's ``FD_GOV_REPO`` at ``repo`` (re-read each call)."""
    if repo:
        os.environ["FD_GOV_REPO"] = str(Path(repo).resolve())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None,
                    help="fd-cn-gov checkout (or a dir holding fd_cn_gov/registry/); "
                         "overrides FD_GOV_REPO")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-eval", action="store_true",
                    help="skip the post-load data evaluation")
    args = ap.parse_args(argv)

    _set_repo(args.repo)

    # Import after FD_GOV_REPO is set so the pack resolves the right path.
    from packs.gov import adapters
    from src.eval.db import connect

    try:
        path = adapters.registry_path()
    except Exception as exc:  # noqa: BLE001 - surface the real reason
        print(f"registry 不可读：{exc}", file=sys.stderr)
        return 1
    print(f"registry: {path}")
    if not path.exists():
        print(f"registry 文件不存在：{path}", file=sys.stderr)
        return 1

    if args.dry_run:
        # Read (not write) so a dry run shows the count and shape.
        records = adapters.read_registry_records()
        print(f"[dry-run] 将落 {len(records)} 条 gov-fact（namespace='gov'）；不写库")
        return 0

    conn = connect()
    try:
        n = adapters.load_gov_registry(conn)
        print(f"落库完成：{n} 条 gov-fact（幂等，重跑不改数）")
        if not args.no_eval:
            # Import the checks module so its gov-fact checkers are registered in
            # THIS process; without it evaluable_kinds(gov) is empty and the eval
            # reports inconclusive (the console imports it at the app edge, but a
            # standalone script must do the same).
            import packs.gov.checks  # noqa: F401
            from src.bench import data_eval

            out = data_eval.run_domain_data_eval(conn, domain_key="gov")
            if not out["run_ids"]:
                print("数据评测：gov 域暂无可评确定性判据（未写入运行）")
            else:
                print(
                    f"数据评测 #{out['run_ids']}：outcome={out['outcome']} "
                    f"通过 {out['n_passed']}/{out['n_criteria']}"
                )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
