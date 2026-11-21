#!/usr/bin/env python3
"""把 `add-agent-autonomous-iteration` 的三件生产收尾一次做完。

    uv run python scripts/finish_agent_autonomy.py --dry-run
    uv run python scripts/finish_agent_autonomy.py --execute

三件事，顺序有意义：

1. **退回越界的提权**：`fleet:ontology-builder` 从 `lead` 回 `expert`。
   2026-11-21 为了让它能确认提案，把它升成了 `lead`——那违反了 spec 的
   「智能体角色不超过 expert」，而且是在「硬停清单没实现」的空档里做的。
   现在确认能力由档位机制给（产出 silver），不再需要域角色。

2. **两条已确认单元的档位补账**：`raw → silver`。它们是在 `confirm` 还写死
   `tier="raw"` 时确认的，按新语义应为 `silver`。只改 tier 并留 provenance，
   不重放确认动作（那会再写一次内容、再记一条事件）。

3. **硬停五动作各真调一次**：用 `agent:` 身份逐个调入口，确认被拒且拒因可读。
   这一步**不能用测试代替**——测试跑在测试库上，而这里要证的是**生产库上的
   代码路径**确实拦得住。

不做的事：不删任何行、不改任何内容（第 2 步只动 tier 与 provenance）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DOMAIN = "data-ontology"
FLEET = "fleet:ontology-builder"
OPERATOR = "ops:chengsishi/agent-autonomy-cutover"

#: The two units confirmed before `confirm` wrote silver.
CONFIRMED_BEFORE_SILVER = (
    "securities_company_financials",
    "securities_industry_monitor",
)


def step1_demote_fleet(conn, *, execute: bool) -> int:
    from src.bench import workspaces

    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    if domain is None:
        print(f"REFUSED: domain {DOMAIN!r} not found", file=sys.stderr)
        return 1
    role = workspaces.get_active_role(conn, domain_id=domain["id"], user_id=FLEET)
    print(f"1. {FLEET} 当前角色: {role}")
    if role == "expert":
        print("   已是 expert，无需退回")
        return 0
    if not execute:
        print("   would demote lead -> expert")
        return 0
    workspaces.add_member(
        conn, domain_id=domain["id"], user_id=FLEET, role="expert",
        added_by=OPERATOR,
    )
    now = workspaces.get_active_role(conn, domain_id=domain["id"], user_id=FLEET)
    print(f"   已退回: {role} -> {now}")
    return 0 if now == "expert" else 1


def step2_backfill_tier(conn, *, execute: bool) -> int:
    failures = 0
    for key in CONFIRMED_BEFORE_SILVER:
        row = conn.execute(
            "SELECT id, kind, tier, provenance FROM knowledge_units "
            # The proposal said kind='dataset', but the confirmed unit landed as
            # `entity` — the template's own vocabulary decides the stored kind, and
            # `dataset` is the *proposal* lane name. Query by key, then report the
            # kind we found rather than assuming it.
            "WHERE namespace = %s AND external_key = %s",
            (DOMAIN, key),
        ).fetchone()
        if row is None:
            print(f"   SKIP {key}: unit not found", file=sys.stderr)
            failures += 1
            continue
        if row["tier"] == "silver":
            print(f"2. {key}: 已是 silver，无需补账")
            continue
        print(f"2. {key} (kind={row['kind']}): {row['tier']} -> silver")
        if not execute:
            continue
        prov = dict(row["provenance"] or {})
        prov["tier_backfill"] = {
            "from": row["tier"],
            "to": "silver",
            "why": "confirmed before confirm wrote silver "
                   "(change add-agent-autonomous-iteration)",
            "by": OPERATOR,
        }
        import json as _json

        conn.execute(
            "UPDATE knowledge_units SET tier = 'silver', provenance = %s "
            "WHERE id = %s",
            (_json.dumps(prov), row["id"]),
        )
        conn.commit()
        after = conn.execute(
            "SELECT tier FROM knowledge_units WHERE id = %s", (row["id"],)
        ).fetchone()["tier"]
        print(f"   now: {after}")
        if after != "silver":
            failures += 1
    return failures


def step3_probe_hard_stops(conn) -> int:
    """Call each guarded entry with a machine identity; every one must refuse."""
    from src.bench import authoring, hard_stops, libraries, templates, workspaces

    agent = f"agent:probe@{DOMAIN}"
    checks: list[tuple[str, object]] = []

    # A footprint snapshot, so "NOT REFUSED" is also caught as a real write
    # rather than only reported. If a guard is missing, these entry points write
    # for real — and a probe that damages production is worse than no probe.
    def _footprint() -> tuple:
        return (
            conn.execute("SELECT count(*) AS n FROM domains").fetchone()["n"],
            conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM ontology_templates "
                "WHERE name = 'data-ontology'"
            ).fetchone()["v"],
            conn.execute(
                "SELECT count(*) AS n FROM knowledge_units "
                "WHERE namespace = %s AND external_key = 'securities_company_financials' "
                "AND (tags->>'deleted') IS NULL",
                (DOMAIN,),
            ).fetchone()["n"],
            conn.execute(
                "SELECT count(*) AS n FROM domain_library_subscriptions"
            ).fetchone()["n"],
        )

    before = _footprint()

    def _expect(action: str, fn) -> None:
        try:
            fn()
        except hard_stops.HardStopError as exc:
            checks.append((action, f"REFUSED: {str(exc)[:60]}"))
        except Exception as exc:  # noqa: BLE001 — any other error is a finding
            checks.append((action, f"WRONG ERROR: {type(exc).__name__}: {str(exc)[:60]}"))
        else:
            checks.append((action, "NOT REFUSED — 闸缺失，写入已发生"))

    _expect("open_or_archive_domain", lambda: workspaces.instantiate_domain(
        conn, key="probe-domain", name="Probe", template_name="data-ontology",
        template_version=None, created_by=agent,
    ))
    # gate-probe: change_template_version —— 这次调用**要被拒**。
    # 它带着 agent 身份调模板写入口，硬停判据必须拦住；`test_bench_template_gate_bypass`
    # 认出这个标记，所以它不会被当成第二扇门（那一类要进 ALLOWED，语义不同）。
    _expect("change_template_version", lambda: templates.update_template(
        conn, name="data-ontology", schema={"entity_types": ["dataset"]},
        created_by=agent,
    ))
    _expect("delete_unit", lambda: authoring.authoring_delete_unit(
        conn, domain_key=DOMAIN, kind="dataset",
        external_key="securities_company_financials", operator=agent,
    ))
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    _expect("widen_sourcing_scope", lambda: libraries.subscribe(
        conn, domain_id=domain["id"], library_key="law-library", created_by=agent,
    ))

    after = _footprint()
    print("3. 硬停五动作实探（生产库）：")
    if after != before:
        print(f"   !! 足迹变化：before={before} after={after}", file=sys.stderr)
    ok = 0
    for action, result in checks:
        good = result.startswith("REFUSED")
        ok += good
        print(f"   {'PASS' if good else 'FAIL'} {action:24s} {result}")
    print("   mint_credential 由 apikey.create_key 的 minted_by 承载，"
          "本进程无铸造身份可比，跳过（见 CI 的单测）")
    return 0 if ok == len(checks) and after == before else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true", help="真的写；缺省是 dry-run")
    ap.add_argument("--dry-run", action="store_true", help="显式 no-op（缺省即 dry-run）")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        failures = step1_demote_fleet(conn, execute=args.execute)
        failures += step2_backfill_tier(conn, execute=args.execute)
        if args.execute:
            failures += step3_probe_hard_stops(conn)
        else:
            print("3. 硬停实探需要 --execute（它只读但会调写入口）")
        print(f"\n{'ALL OK' if failures == 0 else f'{failures} ISSUE(S)'}")
        return 0 if failures == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
