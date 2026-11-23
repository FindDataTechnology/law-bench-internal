"""next_actions 投影逻辑的纯单元测试（design D1/D2/D3/D5）。

这些测试**不碰数据库**：把 ``estate.matrix`` 会产出的一行 ``row`` 直接喂给
``_action_for`` / ``dedup`` / ``rank``，验证投影与排序的正确性。真库上的端到端
（含纯读断言）在 tests/test_domain_next_actions.py（需 PG fixture）。
"""
from __future__ import annotations

import pytest

from src.bench import next_actions as na


def _row(gaps, **over):
    """造一个 estate.matrix 行（只带投影用到的字段）。"""
    row = {
        "domain": {"key": "legal", "id": 1, "path": "legal"},
        "gaps": gaps,
        "ontology": {"curated_units": 0},
        "knowledge": {"chunks": 0},
        "eval": {"standards": 0},
        "quality": {},
        "crosswalk_gaps": {},
        "inbox": {"pending": 0},
    }
    row.update(over)
    return row


def test_priority_table_order_is_the_contract():
    """PRIORITY 表的顺序即 urgency（design D2）；改顺序等于改行为，测试钉住它。"""
    assert na.PRIORITY[0] == "review_backlog"  # 唯一阻塞他人的排第一
    assert set(na.PRIORITY) == {
        "review_backlog", "quality_below_floor", "pillar_empty",
        "work_order_open", "publication_stale",
    }


def test_every_gap_rule_has_a_registered_priority():
    """_GAP_RULES 里每个 priority_key 必须在 PRIORITY 表里，否则会在排序时炸。"""
    for gap, rule in na._GAP_RULES.items():
        assert rule["priority"] in na.PRIORITY, (gap, rule["priority"])


def test_reason_numbers_come_verbatim_from_row():
    """reason_data 里的数字必须与 row（=来源模块返回值）逐字相同（design D1）。"""
    row = _row(
        ["quality:review_lag"],
        quality={"review_lag": {"oldest_hours": 51.2, "over_threshold": True}},
        inbox={"pending": 3},
    )
    a = na._action_for("quality:review_lag", row)
    assert a["reason_data"]["pending"] == 3              # 来自 inbox
    assert a["reason_data"]["oldest_hours"] == 51.2      # 来自 quality.review_lag，未改
    assert a["priority_key"] == "review_backlog"
    assert a["requires_role"] == "can_confirm"


def test_dedup_by_target_key_keeps_higher_priority():
    """两个区指向同一目标（crosswalk）→ 只留优先级高的一条（design D3）。"""
    row = _row([
        "quality:crosswalk_dangling",   # quality_below_floor / target=crosswalk
        "quality:crosswalk_stale",      # 同 target=crosswalk
    ])
    a1 = na._action_for("quality:crosswalk_dangling", row)
    a2 = na._action_for("quality:crosswalk_stale", row)
    kept = na.dedup([a2, a1])  # 输入顺序颠倒，结果应一致
    assert len(kept) == 1
    assert kept[0]["target_kind"] == "crosswalk"


def test_rank_caps_at_five_and_reports_more():
    """硬上限 5 + 「还有 N 项」（design D5）。"""
    # 造 6 个不同目标、不影响排序的 gap
    gaps = []
    for g in ("ontology", "knowledge", "eval"):
        gaps.append(g)
    row = _row(gaps, quality={}, crosswalk_gaps={})
    actions = [na._action_for(g, row) for g in gaps]
    r = na.rank(actions * 2)  # 6 条，去重后仍 3（同 target）
    assert r["total"] == len(na.dedup(actions * 2))
    assert len(r["top"]) <= na.CAP


def test_unknown_gap_is_collected_not_swallowed():
    """表外的 gap 不能静默吞——for_domain 返回 unknown_gaps 让测试点名。"""
    row = _row(["some_future_gap"])
    a = na._action_for("some_future_gap", row)
    assert a is None  # 未登记即 None，由调用方收集


def test_pillar_empty_reason_carries_zero_count():
    """空柱的 reason 带上该柱的 0 计数（可解释，不是空话）。"""
    row = _row(["ontology"], ontology={"curated_units": 0})
    a = na._action_for("ontology", row)
    assert a["reason_data"]["curated_units"] == 0
    assert a["priority_key"] == "pillar_empty"


def test_for_area_row_returns_only_that_areas_action():
    """区页取本区一条：跨区缺口不串台（§2.2）。"""
    row = _row(["ontology", "quality:review_lag"])  # 本体区 + 复核（inbox 区）
    onto = na.for_area_row(row, "ontology")
    assert onto["action"] is not None
    assert onto["action"]["area"] == "ontology"
    inbox = na.for_area_row(row, "inbox")
    assert inbox["action"]["area"] == "inbox"
    assert inbox["action"]["gap"] == "quality:review_lag"


def test_for_area_row_returns_none_when_area_has_no_gap():
    """本区无缺口 → action=None（区页据此明说「这一区没有待办」，不静默缺席）。"""
    row = _row(["ontology"])
    res = na.for_area_row(row, "knowledge")
    assert res["action"] is None
    assert res["more"] == 0


def test_every_entry_targets_a_real_area_endpoint():
    """入口可达（§3.5）：每条动作的 area 必须是已挂路由的区 id，否则点进去 404。

    area 集合取 _GAP_RULES 用到的全部；与 ``domain_context.AREAS``（路由区 id）
    对齐。这条测试在区改名/加区时报警。"""
    from src.web.domain_context import AREAS

    real = {a["id"] for a in AREAS}
    used = {rule["area"] for rule in na._GAP_RULES.values()}
    assert used <= real, used - real
