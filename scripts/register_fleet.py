#!/usr/bin/env python3
"""Register fleets observed in ``domain_proposals.source`` — or name them explicitly.

Why this exists: after ``add-fleet-execution-loop`` a ``fleet:<id>/<post>`` source
must resolve to a live registration bound to the target domain. Production holds
sources written before that rule existed, so the switchover needs one audited
step: enumerate what is actually there, propose a mapping, let a human confirm.

**Nothing here registers automatically.** Turning "a string we once saw" into "an
identity" is exactly the substitution this change removes; ``--from-observed``
therefore only *prints* a proposal, and ``--apply`` requires the operator to have
read it. The probe source ``fleet:credential-probe/post_probe`` is the reason:
it is a real row in production and it is not a fleet, so a machine cannot decide
this.

Run:
    # 1) look, write nothing
    uv run python scripts/register_fleet.py --from-observed --dry-run

    # 2) register one fleet the operator has decided on
    uv run python scripts/register_fleet.py --fleet-ref fleet_1794335712751_wfa3ww \
        --name ontology-fleet-win --domains legal --dry-run
    uv run python scripts/register_fleet.py --fleet-ref fleet_1794335712751_wfa3ww \
        --name ontology-fleet-win --domains legal --apply

    # 3) read the migration counter (must be zero before enforcing strictly)
    uv run python scripts/register_fleet.py --legacy

**An existing registration is promoted in place, never re-registered.** Before this
change every consumer was registered as ``machine``, and some of them are fleets that
are running right now (production: ``ontology-fleet-win``). If the token you pass
already belongs to a registration, ``--apply`` upgrades *that row* —
``kind: machine → fleet`` plus ``fleet_ref`` — and leaves its id, name, credential and
domains alone. Revoking and re-registering would mint a new token and cut the running
fleet off mid-flight, silently.

Exit codes: 0 ok, 1 refused (already registered / bad input), 2 unusable database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _connect():
    """Open the DB the same way the app does (``database_url`` from env or .env)."""
    from src.eval.db import connect  # local import: keeps --help dependency-free

    return connect()


def _observed_fleets(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT split_part(source, '/', 1) AS fleet_part,
               count(*)                  AS n,
               min(submitted_at)         AS first_seen,
               max(submitted_at)         AS last_seen
        FROM domain_proposals
        WHERE source LIKE 'fleet:%%'
        GROUP BY 1
        ORDER BY n DESC, fleet_part
        """
    ).fetchall()
    out = []
    for r in rows:
        ref = (r["fleet_part"] or "").split(":", 1)[1] if r["fleet_part"] else ""
        out.append(
            {
                "fleet_ref": ref,
                "rows": r["n"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            }
        )
    return out


def _print_observed(conn) -> int:
    from src.bench import distribution

    observed = _observed_fleets(conn)
    if not observed:
        print("no fleet:* sources found — nothing to register")
        return 0

    print(f"{len(observed)} fleet ref(s) observed in domain_proposals.source:\n")
    consumers = distribution.list_consumers(conn)
    existing = {c["fleet_ref"]: c for c in consumers if c.get("fleet_ref")}
    for item in observed:
        ref = item["fleet_ref"]
        reg = existing.get(ref)
        if reg is None:
            verdict = "未登记"
        elif reg["revoked_at"] is not None:
            verdict = f"已吊销（{reg['name']}）"
        else:
            verdict = f"已登记（{reg['name']}，域 {reg['domains']}）"
        print(
            f"  {ref:<40} {item['rows']:>4} 行  "
            f"最近 {item['last_seen']}  {verdict}"
        )

    # 本变更之前登记的消费者全是 `machine` 档、没有 fleet_ref，所以上面按 ref 匹配
    # 一律显示「未登记」——而其中就有真正在跑的舰队（产库 `ontology-fleet-win`）。
    # 不替人推断「哪条 machine 就是哪支舰队」（那是这个 change 要拆掉的替换），
    # 但必须把这条路摆出来：新建会撞唯一约束，吊销重登记会换 token 切断它。
    machines = [c for c in consumers if c["kind"] == "machine" and c["revoked_at"] is None]
    if machines:
        print(
            f"\n库里另有 {len(machines)} 条 `machine` 档登记（没有 fleet_ref，上面按 ref 匹配不到）："
        )
        for c in machines:
            print(f"  id={c['id']:<4} {c['name']:<28} 域 {c['domains']}")
        print(
            "  其中若有**就是**上面某支舰队的老登记：给出它**自己的** token 跑 --apply，"
            "本脚本会**原地升级**（machine → fleet，凭据不变、客户端无感）。\n"
            "  不要吊销重登——那会发一枚新 token，把正在跑的舰队当场切断。"
        )

    print(
        "\n这不是一份可以直接 apply 的清单：探针来源（如 credential-probe）也在这里，"
        "\n它不是一个舰队。逐个确认后用 --fleet-ref / --domains 显式登记。"
    )
    return 0


def _register(
    conn,
    *,
    fleet_ref: str,
    name: str,
    domains: list[str],
    token_hash: str,
    apply: bool,
    set_domains: bool = False,
) -> int:
    from src.bench import distribution

    requested_name = (name or "").strip()
    inferred_name = requested_name or f"fleet-{fleet_ref}"
    existing = distribution.get_consumer_by_token_hash(conn, token_hash=token_hash)

    print(f"fleet_ref : {fleet_ref}")
    print(f"name      : {inferred_name}")
    print(f"domains   : {domains}")
    print(f"kind      : fleet")
    print(f"credential: sha256:{token_hash[:12]}… (never printed in full)")

    if existing is not None:
        return _promote(
            conn,
            existing=existing,
            fleet_ref=fleet_ref,
            requested_name=requested_name,
            domains=domains,
            token_hash=token_hash,
            apply=apply,
            set_domains=set_domains,
        )

    # 名字被别的登记占着、而凭据又不是它那枚 ⇒ 两条唯一约束都会撞。先判再写：
    # 一份 dry run 说「会登记」而 apply 当场失败，是最误导的一种报错。
    same_name = next(
        (c for c in distribution.list_consumers(conn) if c["name"] == inferred_name), None
    )
    if same_name is not None:
        print(
            f"refused: 名字 {inferred_name!r} 已被 id={same_name['id']} 占用"
            f"（kind={same_name['kind']}），而它的凭据与 {fleet_ref!r} 这枚不同。\n"
            f"  要升级那条既有登记：把 token 换成**它自己的**那枚，本脚本会原地升级；\n"
            f"  要新登记一条：换一个 --name。",
            file=sys.stderr,
        )
        return 1

    if not apply:
        print("\n(would register a NEW consumer; dry run — nothing written, re-run with --apply)")
        return 0

    try:
        consumer = distribution.register_consumer(
            conn,
            name=inferred_name,
            domains=domains,
            token_hash=token_hash,
            created_by="register_fleet.py",
            kind="fleet",
            fleet_ref=fleet_ref,
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"\nregistered id={consumer['id']} name={consumer['name']!r}")
    return 0


def _promote(
    conn,
    *,
    existing: dict,
    fleet_ref: str,
    requested_name: str,
    domains: list[str],
    token_hash: str,
    apply: bool,
    set_domains: bool,
) -> int:
    """Upgrade the registration that already holds this credential: machine → fleet.

    为什么不是「吊销再登记」：那会换掉 token，而 token 正是这枚凭据——
    在跑的舰队会被当场切断，而它自己完全不知道发生了什么。
    """
    from src.bench import distribution

    stored = sorted(existing["domains"] or [])
    wanted = sorted({d.strip() for d in domains if d and d.strip()})
    print(
        f"existing  : id={existing['id']} name={existing['name']!r} "
        f"kind={existing['kind']} fleet_ref={existing['fleet_ref']} domains={stored}"
    )

    if existing["revoked_at"] is not None:
        print(
            f"refused: 登记 {existing['name']!r} 已吊销；吊销的登记不升级"
            "（它的凭据已经不作数了），改用一枚新凭据登记新的一条。",
            file=sys.stderr,
        )
        return 1
    if requested_name and requested_name != existing["name"]:
        print(
            f"refused: 这枚凭据属于登记 {existing['name']!r}，不是 {requested_name!r}。\n"
            "  升级只动 kind / fleet_ref，不改名、不改凭据——去掉 --name，或写该登记的名字。",
            file=sys.stderr,
        )
        return 1
    if wanted != stored and not set_domains:
        print(
            f"refused: 域绑定不一致（库里 {stored}，命令行 {wanted}）。\n"
            "  升级不改域：确认要用命令行这份就加 --set-domains；否则把 --domains 写成库里的值。",
            file=sys.stderr,
        )
        return 1

    change = f"kind={existing['kind']} → fleet, fleet_ref → {fleet_ref!r}"
    if wanted != stored:
        change += f", domains {stored} → {wanted}"
    if existing["kind"] == "fleet" and existing["fleet_ref"] == fleet_ref and wanted == stored:
        print(
            f"\nnothing to change: id={existing['id']} {existing['name']!r} is already a fleet "
            f"under {fleet_ref!r} with domains {stored}."
        )
        return 0
    if not apply:
        print(f"\n(would PROMOTE id={existing['id']} in place: {change}; name/credential unchanged)")
        print("(dry run — nothing written, re-run with --apply)")
        return 0

    try:
        if wanted != stored:
            distribution.set_consumer_domains(conn, name=existing["name"], domains=wanted)
        consumer = distribution.promote_consumer_to_fleet(
            conn, token_hash=token_hash, fleet_ref=fleet_ref
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(
        f"\npromoted id={consumer['id']} name={consumer['name']!r}: {change}"
        f"（凭据未变，客户端无感）"
    )
    return 0


def _legacy(conn) -> int:
    """Print the migration counter **and how to read it**.

    「数到 0」是一条错判据：历史行不会消失，所以总数永远不会是 0（产库那条
    `fleet:credential-probe/post_probe` 探针就是永久一组——它不是一个舰队，
    永远不该被登记）。真正决定能不能翻硬的问题只有一个：

        **现在还活着的提交方，有没有谁的新提交会被拒？**

    历史行只说明过去写过什么；strict 档拒绝的是**新提交**。所以判据是「每个仍有
    客户端的来源都已登记」，不是「这张表空了」。
    """
    from src.bench import proposals

    rows = proposals.legacy_sources(conn)
    mode = proposals._submitter_mode()
    print(f"enforcement mode: {mode}")
    if not rows:
        print("legacy sources: none — the window can close")
        return 0
    unknown = sum(r["n"] for r in rows if r["verdict"] is None)
    print(f"legacy sources: {len(rows)} group(s)")
    for r in rows:
        # NULL 是「写入时还没有这一列」的历史行：它是货真价实的遗留，但它没有
        # 任何判定可读，所以单独标出来，不假装成某个 verdict。
        verdict = r["verdict"] or "(历史行·无判定)"
        print(f"  {r['source']:<50} {verdict:<24} {r['n']:>4} 行")

    # 这一组提示是这条命令的重点：没有它，「数还没到 0」会被读成「还不能翻硬」，
    # 而实际上可能只差一条永远不会再提交的历史探针。
    live_risk = [
        r for r in rows
        if (r["verdict"] in (None, "unregistered", "revoked", "domain_mismatch",
                             "unknown_prefix", "malformed", "user_mismatch",
                             "agent_domain_mismatch", "agent_not_member"))
    ]
    print(
        "\n怎么读这个数：**不要**等它变成 0——历史行不会消失。要问的是"
        "「现在还在提交的来源里，有谁的**新提交**会被拒」。"
    )
    if unknown:
        print(
            f"  · {unknown} 行没有判定（列不存在时写入）：它们只说明历史，"
            "不会再提交；除非那正是某个仍在跑的来源的旧形态。"
        )
    if live_risk:
        print("  · 下列来源若**现在**再提交会被拒——先确认它是否还有客户端在跑，"
              "有就登记，没有就记为历史：")
        for r in live_risk:
            print(f"      {r['source']}  ({r['verdict'] or '无判定'})")
    else:
        print("  · 剩余各组都不是「会被拒」的形态，可以翻硬。")
    print(
        f"\n翻硬 = 不再设 {proposals._SUBMITTER_MODE_ENV}（默认即 strict）。"
        "翻转后本条命令仍会列出同样的历史行，这是预期的。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-observed", action="store_true",
                    help="print fleet refs found in domain_proposals.source (never writes)")
    ap.add_argument("--fleet-ref", help="bare fleet id, e.g. fleet_1794335712751_wfa3ww")
    ap.add_argument("--name", help="registration name (default: fleet-<ref>)")
    ap.add_argument("--domains", nargs="+", default=[], help="domain keys this fleet may submit to")
    ap.add_argument(
        "--token-env",
        default="BENCH_FLEET_TOKEN",
        help="env var holding the fleet's EXISTING plaintext token (hashed here, never echoed). "
             "Required for --apply: a new credential would cut the running fleet off.",
    )
    ap.add_argument("--legacy", action="store_true", help="print the migration counter")
    ap.add_argument(
        "--set-domains",
        action="store_true",
        help="when promoting an existing registration, also update its bound domains to --domains "
             "(refused by default: promotion changes kind/fleet_ref only)",
    )
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    args = ap.parse_args(argv)

    if not (args.from_observed or args.legacy or args.fleet_ref):
        ap.error("nothing to do: pass --from-observed, --legacy, or --fleet-ref")

    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001 - an unusable DB must not look like success
        print(f"cannot reach the database: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    try:
        try:
            return _dispatch(conn, args)
        except Exception as exc:  # noqa: BLE001
            # 连得上但表不存在＝这个库没跑过建库步骤（本机 dev 常如此，测试都建
            # 自己的临时库）。报数据表缺失比一份裸 traceback 有用得多。
            if type(exc).__name__ == "UndefinedTable":
                print(
                    f"这个数据库里没有 bench 的表（{exc}）。\n"
                    "  它还是一个空库：先跑建库步骤（ensure_schema）或指向真正有数据的库。",
                    file=sys.stderr,
                )
                return 2
            raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _dispatch(conn, args) -> int:
    if args.legacy:
        return _legacy(conn)
    if args.from_observed:
        return _print_observed(conn)

    if not args.domains:
        print("refused: --domains is required (a fleet with no domain can submit nowhere)",
              file=sys.stderr)
        return 1

    plaintext = (os.environ.get(args.token_env) or "").strip()
    if not plaintext:
        print(
            f"refused: set {args.token_env} to the fleet's existing token first.\n"
            "  Registering a *new* credential would cut the running fleet off; this "
            "script will not invent one.",
            file=sys.stderr,
        )
        return 1
    import hashlib

    token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    return _register(
        conn, fleet_ref=args.fleet_ref.strip(), name=(args.name or "").strip(),
        domains=[d.strip() for d in args.domains if d.strip()],
        token_hash=token_hash, apply=args.apply, set_domains=args.set_domains,
    )


if __name__ == "__main__":
    raise SystemExit(main())
