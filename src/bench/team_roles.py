"""只读岗位：巡检员（warden）与质检员（verifier）。

这两个岗位是团队的**第一支**，选它们打头是因为它们不改本体：一个把缺口变成任务，
一个把噪声从人眼前拿掉。跑错了最坏的结果是"报告不准"，不是"写脏了库"。

三条纪律：

- **只读**：这里没有任何写库路径（除了台账与派单）。发现问题出结论，不动数据。
- **质检员不看起草思路**：它拿到的是产物 + 当前本体，回源核对；起草者的解释不在
  输入里。否则"独立检查"只是自我复述。
- **不确定就报不确定**：逐字核对需要语料原文，拿不到时报 ``unknown`` 而不是
  ``pass``。把"没法验"记成"验过了"，是这套东西最不能犯的错。
"""

from __future__ import annotations

from typing import Any, Optional

from . import agent_ids, agent_runs, dispatch, estate, proposals, workspaces

#: 缺口 → 该由谁处理。``None`` = 人（复核积压不是智能体能替的）。
GAP_OWNER: dict[str, Optional[str]] = {
    "ontology": "builder",
    "knowledge": "scout",
    "eval": "eval",
    "quality:grounding": "concept",
    "quality:evidence": "builder",
    "quality:referential": "verifier",
    "quality:key_hygiene": "builder",
    "quality:review_lag": None,
}

#: 质检员能机器判定的项。顺序即报告顺序（先便宜且确定的后贵的）。
VERIFIER_CHECKS = (
    "key_already_live",      # 键已在库里：连"要不要写"都不用判
    "missing_evidence",      # 没有可回源的依据
    "endpoint_open",         # 关系端点未闭合
    "near_duplicate",        # 同一实体的另一种写法已在本体
    "quote_unverifiable",    # 有引文但本轮无法回源核对
)


def _role(role: str, domain_key: str) -> str:
    return agent_ids.agent_identity(role, domain_key)


def _finish_failed(conn: Any, run_id: int, exc: BaseException) -> None:
    """记下失败，**先回滚**再写。

    失败的来源常常是一条 SQL 报错（表缺失、约束冲突），此时连接已处于中止事务
    状态：不回滚就去写台账，写台账本身会再失败——于是"失败一定留痕"这条承诺
    在最需要它的时刻失效，而且现场只剩一句 InFailedSqlTransaction。
    """
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 - 回滚失败也不能掩盖原始错误
        pass
    try:
        agent_runs.finish(conn, run_id=run_id, outcome="failed",
                          detail=f"{type(exc).__name__}: {exc}"[:300])
    except Exception:  # noqa: BLE001 - 台账写不进去时，原始异常必须继续抛
        pass


def run_warden(conn: Any, *, domain_key: str, limit: int = 50) -> dict:
    """巡检一轮：缺口 → 质量比 → 派单 → 台账。不写本体。"""
    role = _role("warden", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"warden-{domain_key}")
    try:
        domain = workspaces.get_domain(conn, domain_key=domain_key)
        if domain is None:
            raise ValueError(f"domain {domain_key!r} not found")
        rows = estate.matrix(conn, domains=[domain])
        row = rows[0]
        gaps = list(row["gaps"])

        created, already, skipped = 0, 0, []
        for gap in gaps:
            owner = GAP_OWNER.get(gap)
            if owner is None:
                skipped.append(gap)          # 复核积压归人，不派给智能体
                continue
            out = dispatch.dispatch(
                conn, rows=rows, gap=gap,
                assignee=_role(owner, domain_key), created_by=role,
            )
            created += len(out["created"])
            already += len(out["already_open"])

        # 计数键不能叫 "gaps"：返回体里已经有 gaps（列表），用 **counts 展开会把
        # 列表覆盖成整数，调用方拿到一个 len() 不了的数字。
        counts = {"gap_count": len(gaps), "tasks_created": created,
                  "already_open": already, "skipped": skipped}
        detail = None if gaps else "无缺口"
        finished = agent_runs.finish(conn, run_id=run["id"], outcome="ok",
                                     counts=counts, artifact_refs=[], detail=detail)
        return {"run": finished, "gaps": gaps, **counts}
    except Exception as exc:  # noqa: BLE001 - 台账必须记下失败本身的形状
        _finish_failed(conn, run["id"], exc)
        raise


def run_verifier(conn: Any, *, domain_key: str, limit: int = 200) -> dict:
    """质检一轮：把不值得人看的提案标出来。不改提案状态，不写本体。"""
    role = _role("verifier", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"verifier-{domain_key}")
    try:
        domain = workspaces.get_domain(conn, domain_key=domain_key)
        if domain is None:
            raise ValueError(f"domain {domain_key!r} not found")
        live = agent_ids_live_keys(conn, domain_key=domain_key)
        rel_kinds = _relationship_kinds(conn, domain)
        pending = proposals.list_proposals(conn, domain_key=domain_key,
                                           state="pending", limit=limit)
        findings = _inspect(pending, live=live, rel_kinds=rel_kinds)

        by_check: dict[str, int] = {}
        for f in findings:
            by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        clean = len(pending) - len({f["proposal_id"] for f in findings})
        counts = {"pending": len(pending), "flagged": len({f["proposal_id"] for f in findings}),
                  "clean": clean, "by_check": by_check}

        # 薄不薄看"有多少条其实不用人看"：一条都没标出来时，人不该以为质检白跑，
        # 那说明这批提案本来就干净，所以给 ok；只有当输入为空时才是 thin。
        outcome = "thin" if not pending else "ok"
        finished = agent_runs.finish(
            conn, run_id=run["id"], outcome=outcome, counts=counts,
            artifact_refs=[{"batch": p["batch"]} for p in _batches(pending)],
            detail=None if pending else "没有待确认提案",
        )
        return {"run": finished, "findings": findings, **counts}
    except Exception as exc:  # noqa: BLE001
        _finish_failed(conn, run["id"], exc)
        raise


def agent_ids_live_keys(conn: Any, *, domain_key: str) -> dict[str, str]:
    """``{key: kind}`` of live units — the set a proposal is checked against."""
    from . import authoring

    return authoring.authoring_live_key_kinds(conn, domain_key=domain_key)


def _relationship_kinds(conn: Any, domain: dict) -> set[str]:
    from . import templates

    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    kinds = schema.get("relationship_kinds")
    return {str(k) for k in kinds} if isinstance(kinds, list) else set()


def _inspect(pending: list[dict], *, live: dict[str, str],
             rel_kinds: set[str]) -> list[dict]:
    """四类机器判定 + 一类"没法验"。返回 findings，不改任何东西。"""
    findings: list[dict] = []
    seen_keys: dict[str, list[dict]] = {}
    for p in pending:
        key = (p.get("external_key") or "").strip()
        kind = p.get("kind") or ""
        seen_keys.setdefault(key, []).append(p)

        if key and key in live:
            findings.append(_finding(p, "key_already_live",
                                     f"键已存在于本体（kind={live[key]}）"))
            continue

        evidence = p.get("evidence") or {}
        if kind in rel_kinds:
            frm = evidence.get("from_key") or evidence.get("from")
            to = evidence.get("to_key") or evidence.get("to")
            if not frm or not to:
                findings.append(_finding(p, "missing_evidence",
                                         "关系提案缺少 from_key/to_key"))
                continue
            missing = [k for k in (frm, to) if k not in live]
            if missing:
                findings.append(_finding(p, "endpoint_open",
                                         f"端点不存在：{missing}"))
                continue
        else:
            if not evidence:
                findings.append(_finding(p, "missing_evidence", "没有依据"))
                continue
            if isinstance(evidence, dict) and "quote" in evidence:
                # 逐字核对需要语料原文；本轮拿不到就如实报"没法验"，
                # 不能报通过——那等于替人签了字。
                findings.append(_finding(p, "quote_unverifiable",
                                         "有引文但本轮未回源核对"))

    # 同一实体的两种写法：同键多条（跨来源）在 pending 里就是重复主张
    for key, group in seen_keys.items():
        if len(group) > 1:
            for p in group[1:]:
                findings.append(_finding(p, "near_duplicate",
                                         f"与提案 {group[0]['id']} 同键"))
    return findings


def _finding(proposal: dict, check: str, note: str) -> dict:
    return {"proposal_id": proposal["id"], "check": check, "note": note,
            "kind": proposal.get("kind"), "external_key": proposal.get("external_key"),
            "batch": proposal.get("batch") or _batch_of(proposal)}


def _batch_of(proposal: dict) -> Optional[str]:
    ev = proposal.get("evidence")
    return ev.get("batch") if isinstance(ev, dict) else None


def _batches(pending: list[dict]) -> list[dict]:
    return [{"batch": b} for b in {_batch_of(p) for p in pending} if b]
