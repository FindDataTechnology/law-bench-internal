"""Domain "next action" projection (openspec: add-domain-next-actions).

## 这是投影，不是计算（design D1）

``for_domain()`` **不新算任何数**：它读既有模块的返回值（``estate.matrix`` 的缺口矩阵
``row["gaps"]``、``row["quality"]`` 的比率、``row["inbox"]`` 的待确认计数），把「缺口 +
数字 + 状态」翻译成 ``(reason, action, entry, priority_key, requires_role)``。理由里的每个
数字都逐字取自来源模块——本模块不做除法、不四舍五入。

## 优先级是显式表（design D2）

``PRIORITY`` 顺序即 urgency；表外的键即 ``KeyError``。

## 去重按目标键（design D3）

同一批提案会被「复核积压 quality:review_lag」与「提案箱待确认 inbox」同时指向；去重键
``(target_kind, target_key)``，保留优先级高的一条。不按文案去重。

## 入口可达性（design D4）

每条动作带 ``requires_role``（键来自既有 ``capability()`` 的 ``can_*`` 判定名）。
渲染层据此决定给链接还是「需要〈角色〉」。``entry`` 是 url path 段，由渲染层 ``url_for`` 解析。
"""
from __future__ import annotations

from typing import Any, Optional

# 顺序即优先级（design D2）。表外的 priority_key 即报错。
PRIORITY: tuple[str, ...] = (
    "review_backlog",       # 有人在等确认 —— 唯一会阻塞他人的
    "quality_below_floor",  # 有内容但立不住
    "pillar_empty",         # 没有内容
    "work_order_open",      # 已派的活没做完
    "publication_stale",    # 发布面过期
)
_PRIORITY_RANK = {k: i for i, k in enumerate(PRIORITY)}

#: 清单硬上限（design D5）。
CAP = 5

#: 每个缺口字符串 → (priority_key, area, action 键, requires_role 键, target_kind)。
#: area 拼成入口 ``/d/<key>/<area>``。action / requires_role 是 i18n / capability 的键，
#: 不在本模块写文案。表外的缺口（未来新增的 gap）不静默吞——落到 ``_unknown`` 由测试点名。
_GAP_RULES: dict[str, dict[str, str]] = {
    "quality:review_lag": {
        "priority": "review_backlog", "area": "inbox",
        "action": "next_action.action.review_backlog",
        "requires_role": "can_confirm", "target": "proposal_backlog"},
    "quality:crosswalk_dangling": {
        "priority": "quality_below_floor", "area": "ontology",
        "action": "next_action.action.crosswalk_dangling",
        "requires_role": "can_write", "target": "crosswalk"},
    "quality:crosswalk_stale": {
        "priority": "quality_below_floor", "area": "ontology",
        "action": "next_action.action.crosswalk_stale",
        "requires_role": "can_write", "target": "crosswalk"},
    "quality:crosswalk_unconfirmed": {
        "priority": "quality_below_floor", "area": "ontology",
        "action": "next_action.action.crosswalk_unconfirmed",
        "requires_role": "can_confirm", "target": "crosswalk"},
    "quality:crosswalk": {
        "priority": "quality_below_floor", "area": "ontology",
        "action": "next_action.action.crosswalk_coverage",
        "requires_role": "can_write", "target": "crosswalk"},
    "quality:template": {
        "priority": "quality_below_floor", "area": "eval-standards",
        "action": "next_action.action.template_undeclared",
        "requires_role": "can_write", "target": "eval_standards"},
    "quality:evidence": {
        "priority": "quality_below_floor", "area": "library",
        "action": "next_action.action.evidence_below_floor",
        "requires_role": "can_write", "target": "library"},
    "quality:grounding": {
        "priority": "quality_below_floor", "area": "knowledge",
        "action": "next_action.action.grounding_below_floor",
        "requires_role": "can_write", "target": "knowledge"},
    "quality:referential": {
        "priority": "quality_below_floor", "area": "knowledge",
        "action": "next_action.action.referential",
        "requires_role": "can_write", "target": "knowledge"},
    "quality:key_hygiene": {
        "priority": "quality_below_floor", "area": "team",
        "action": "next_action.action.key_hygiene",
        "requires_role": "can_manage_members", "target": "keys"},
    "ontology": {
        "priority": "pillar_empty", "area": "ontology",
        "action": "next_action.action.ontology_empty",
        "requires_role": "can_write", "target": "ontology"},
    "knowledge": {
        "priority": "pillar_empty", "area": "knowledge",
        "action": "next_action.action.knowledge_empty",
        "requires_role": "can_write", "target": "knowledge"},
    "eval": {
        "priority": "pillar_empty", "area": "eval-standards",
        "action": "next_action.action.eval_empty",
        "requires_role": "can_write", "target": "eval_standards"},
}


def _action_for(gap: str, row: dict) -> Optional[dict]:
    """Translate one gap into an action row, pulling the reason number verbatim
    from ``row`` (design D1: no arithmetic here).

    返回 dict 或 None（未知 gap 由调用方收集点名，不静默吞）。
    """
    rule = _GAP_RULES.get(gap)
    if rule is None:
        return None
    domain = row["domain"]
    reason = _reason_for(gap, row)
    return {
        "gap": gap,
        "priority_key": rule["priority"],
        "action": rule["action"],
        "entry": f"/d/{domain['key']}/{rule['area']}",
        "requires_role": rule["requires_role"],
        "target_kind": rule["target"],
        "target_key": domain["key"],  # 未细分的 gap 以域为目标；细分见 _reason_for
        "reason_data": reason,        # 结构化数字，渲染层映 i18n 模板
    }


def _reason_for(gap: str, row: dict) -> dict:
    """把该 gap 的数字从 row 里**原样**取出（不做除法/四舍五入）。

    返回一个 ``{key: value}`` 字典供 i18n 模板插值；值全部来自来源模块。
    测试断言「这里取出的数字 == 来源模块返回的数字」。
    """
    q = row.get("quality") or {}
    if gap == "quality:review_lag":
        m = q.get("review_lag") or {}
        return {"pending": (row.get("inbox") or {}).get("pending", 0),
                "oldest_hours": m.get("oldest_hours")}
    if gap in ("quality:crosswalk", "quality:crosswalk_dangling",
               "quality:crosswalk_stale", "quality:crosswalk_unconfirmed"):
        m = q.get("crosswalk") or {}
        cg = row.get("crosswalk_gaps") or {}
        return {"value": m.get("value"), "numerator": m.get("numerator"),
                "denominator": m.get("denominator"),
                "dangling": len(cg.get("dangling") or []),
                "stale": len(cg.get("stale") or []),
                "unconfirmed": len(cg.get("unconfirmed") or [])}
    if gap == "quality:template":
        m = q.get("template") or {}
        return {"value": m.get("value"), "undeclared": bool(m.get("undeclared"))}
    if gap.startswith("quality:"):
        name = gap.split(":", 1)[1]
        m = q.get(name) or {}
        return {"value": m.get("value"), "numerator": m.get("numerator"),
                "denominator": m.get("denominator")}
    # pillar 空：把该柱的 0 计数带出（有数字更可解释）
    if gap == "ontology":
        return {"curated_units": (row.get("ontology") or {}).get("curated_units")}
    if gap == "knowledge":
        return {"chunks": (row.get("knowledge") or {}).get("chunks")}
    if gap == "eval":
        return {"standards": (row.get("eval") or {}).get("standards")}
    return {}


def dedup(actions: list[dict]) -> list[dict]:
    """按 ``(target_kind, target_key)`` 去重，保留优先级高的一条（design D3）。

    不按 reason 文案去重——文案是模板，可翻译。输入顺序不影响结果：先按优先级
    排序，再保留每个目标键首次出现的一条。
    """
    ordered = sorted(actions, key=lambda a: _PRIORITY_RANK[a["priority_key"]])
    seen: set[tuple[str, str]] = set()
    out = []
    for a in ordered:
        k = (a["target_kind"], a["target_key"])
        if k in seen:
            continue
        seen.add(k)
        out.append(a)
    return out


def rank(actions: list[dict], *, cap: int = CAP) -> dict:
    """排序 + 去重 + 截断（design D5）。返回 {top, more, total}。

    排序稳定：同 priority_key 按 priority_key 在 PRIORITY 表内的位置——本函数保证
    调用方拿到的顺序可解释（表即解释）。
    """
    deduped = dedup(actions)
    total = len(deduped)
    return {
        "top": deduped[:cap],
        "more": max(0, total - cap),
        "total": total,
    }


def for_row(row: dict) -> dict:
    """从**已算好的** estate.matrix 一行投影下一动作（design D1：不重跑 matrix）。

    域列表/矩阵已有一整批 ``all_rows``；对每个域调 ``for_domain`` 会重新跑 matrix
    （每个域一次外部计数）——这里直接吃现成的 row，避免重复查询，也保证列表摘要与
    总览清单同源同值。
    """
    actions: list[dict] = []
    unknown: list[str] = []
    for gap in row.get("gaps") or []:
        a = _action_for(gap, row)
        if a is None:
            unknown.append(gap)
        else:
            actions.append(a)
    return {"ranked": rank(actions), "unknown_gaps": unknown}


def for_domain(conn: Any, domain: dict, *, probed: Optional[dict] = None) -> dict:
    """一个域的下一动作（投影，不计算）。

    读 ``estate.matrix`` 对该域产出的一行，交给 :func:`for_row` 投影。纯读。

    返回 ``{"ranked": {top, more, total}, "unknown_gaps": [...]}``。
    """
    from . import estate as _estate

    rows = _estate.matrix(conn, domains=[domain], probed=probed)
    if not rows:
        return {"ranked": {"top": [], "more": 0, "total": 0}, "unknown_gaps": []}
    return for_row(rows[0])
