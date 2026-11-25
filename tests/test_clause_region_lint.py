"""Tests for the clause region-lint (``src.clauses.audit.region_lint``).

Hermetic: pure regex, no LLM, no database, no network. This lint is both a
pre-filter (region_leak candidates) and the post-rewrite quality metric
(rewritten clauses must show 0 matches), so a miss is a silent "clean" on a
clause that still names a local regulation or agency.
"""

from __future__ import annotations

import pytest

from src.clauses.audit import region_lint


@pytest.mark.parametrize(
    "body,expected",
    [
        # local-regulation citations
        ("《深圳市员工工资支付条例》另有规定的，从其规定。", "深圳市员工工资支付条例"),
        ("依照广东省工资支付条例执行。", "广东省工资支付条例"),
        # bare locality-binding qualifiers
        ("按照广东省现行规定办理。", "广东省现行规定"),
        ("依据深圳市有关规定处理。", "深圳市有关规定"),
        # local agencies — 局 / 厅
        ("北京市工商局负责登记。", "北京市工商局"),
        ("广东省住建厅负责监督。", "广东省住建厅"),
        # local agencies — 委 (abbreviation of 委员会; the form the list missed)
        ("由北京市住建委负责监管。", "北京市住建委"),
        ("北京市发改委负责审批。", "北京市发改委"),
        ("深圳市住建委备案。", "深圳市住建委"),
        ("广东省卫健委指导。", "广东省卫健委"),
        # full 委员会 still matches
        ("深圳市市场监督管理局负责。", "深圳市市场监督管理局"),
    ],
)
def test_region_lint_flags_local_references(body: str, expected: str):
    hits = region_lint(body)
    assert hits, f"expected a region hit in {body!r}"
    assert any(expected in h for h in hits), f"{expected!r} not among {hits}"


@pytest.mark.parametrize(
    "body",
    [
        "本合同由双方协商订立，违约方承担违约责任。",
        # national-level names are explicitly NOT flagged
        "依照中华人民共和国劳动合同法处理。",
        "任何一方不得违反全国性的强制性规定。",
    ],
)
def test_region_lint_leaves_generic_text_clean(body: str):
    assert region_lint(body) == []


def test_region_lint_empty_and_none_are_safe():
    assert region_lint("") == []
    assert region_lint(None) == []  # type: ignore[arg-type]


def test_region_lint_dedupes_repeated_hits():
    body = "深圳市住建委负责；另按深圳市住建委要求办理。"
    hits = region_lint(body)
    assert hits.count("深圳市住建委") == 1
