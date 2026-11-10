"""确定性接地：概念挂到正文里逐字出现它的条款上。

要钉住的是"接地的判据是可核对的"，不是"挂得多"：

- 只接**逐字出现**的：不做同义、不做 stemming；
- 一条概念最多接一条：接地率要的是"有没有落点"，多挂只会让图变成噪声；
- 已有接地的概念不再接（幂等）；
- 一条都不匹配的概念如实计入 `no_clause_mentions`，不编一个落点。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401
from src.bench import authoring, grounding, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _unit(conn, kind, key, body):
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind=kind, external_key=key, body=body, operator="t")


# ── plan ────────────────────────────────────────────────────────────────────


def test_a_verbatim_mention_is_a_candidate(conn):
    _unit(conn, "concept", "举证责任", "举证责任")
    _unit(conn, "clause", "合同法#第64条", "当事人对自己提出的主张，有责任提供证据。")
    _unit(conn, "clause", "民法典#第1条", "为了保护民事主体的合法权益。")
    out = grounding.plan(conn, domain_key="legal")
    assert out["groundable"] == 0, "没有逐字出现就不接"
    assert out["no_clause_mentions"] == 1


def test_plan_picks_the_shortest_matching_clause(conn):
    _unit(conn, "concept", "违约金", "违约金")
    _unit(conn, "clause", "合同法#第114条",
          "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金。")
    _unit(conn, "clause", "合同法#第115条", "违约金")
    picks = grounding.plan(conn, domain_key="legal")["picks"]
    assert len(picks) == 1
    assert picks[0]["clause"] == "合同法#第115条", "最短正文优先"
    assert picks[0]["concept"] == "违约金"
    assert "违约金" in picks[0]["snippet"]


def test_plan_is_one_relation_per_concept(conn):
    _unit(conn, "concept", "定金", "定金")
    for i in (1, 2, 3):
        _unit(conn, "clause", f"合同法#第{i}条", f"第{i}条 定金规则")
    picks = grounding.plan(conn, domain_key="legal")["picks"]
    assert len([p for p in picks if p["concept"] == "定金"]) == 1


def test_an_already_grounded_concept_is_not_replanned(conn):
    _unit(conn, "concept", "定金", "定金")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="defines",
        from_key="定金", to_key="合同法#第1条", body="x", operator="t")
    out = grounding.plan(conn, domain_key="legal")
    assert out["already_grounded"] == 1
    assert out["picks"] == []


def test_dry_run_writes_nothing(conn):
    _unit(conn, "concept", "定金", "定金")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    out = grounding.ground_concepts(conn, domain_key="legal", dry_run=True)
    assert out["created"] == 0 and out["dry_run"] is True
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE kind='defines'").fetchone()["n"] == 0


# ── apply ───────────────────────────────────────────────────────────────────


def test_apply_creates_the_relation_through_the_kernel(conn):
    _unit(conn, "concept", "定金", "定金")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    out = grounding.ground_concepts(conn, domain_key="legal", dry_run=False)
    assert out["created"] == 1
    rel = conn.execute(
        "SELECT external_key, attrs FROM knowledge_units WHERE kind='defines'").fetchone()
    assert rel["external_key"] == "定金->defines:合同法#第1条"
    assert rel["attrs"]["via"] == "deterministic-mention"
    assert "定金" in rel["attrs"]["matched_text"]


def test_apply_is_idempotent(conn):
    _unit(conn, "concept", "定金", "定金")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    grounding.ground_concepts(conn, domain_key="legal", dry_run=False)
    again = grounding.ground_concepts(conn, domain_key="legal", dry_run=False)
    assert again["created"] == 0


def test_after_reports_the_ratio_and_what_stays_ungrounded(conn):
    _unit(conn, "concept", "定金", "定金")
    _unit(conn, "concept", "举证责任", "举证责任")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    out = grounding.ground_concepts(conn, domain_key="legal", dry_run=False)
    report = grounding.after(conn, domain_key="legal")
    assert out["created"] == 1
    assert report["concepts"] == 2 and report["grounded"] == 1
    assert report["ratio"] == 0.5
    assert report["ungrounded"] == ["举证责任"]


def test_a_concept_with_no_mention_is_left_ungrounded(conn):
    _unit(conn, "concept", "举证责任", "举证责任")
    _unit(conn, "clause", "合同法#第1条", "定金规则")
    out = grounding.ground_concepts(conn, domain_key="legal", dry_run=False)
    assert out["created"] == 0
    assert out["no_clause_mentions"] == 1


def test_a_generic_name_is_not_auto_anchored(conn):
    """泛称在太多条款里出现时没有唯一定义条，留给人工，不硬挑一条。

    实测：行政处罚在 13 条里出现、合同解除在 10 条里——挑最短的那条是任意的。
    """
    _unit(conn, "concept", "行政处罚", "行政处罚")
    for i in range(1, 6):
        _unit(conn, "clause", f"某条例#第{i}条", f"第{i}条 行政处罚的程序")
    out = grounding.plan(conn, domain_key="legal", max_candidates=3)
    assert out["picks"] == []
    assert out["too_generic"] == [{"concept": "行政处罚", "candidates": 5}]


def test_a_specific_name_within_the_limit_is_still_anchored(conn):
    _unit(conn, "concept", "举证责任", "举证责任")
    _unit(conn, "clause", "民事诉讼法#第67条", "当事人对自己提出的主张，有责任提供证据。举证责任")
    out = grounding.plan(conn, domain_key="legal", max_candidates=3)
    assert [p["concept"] for p in out["picks"]] == ["举证责任"]
    assert out["too_generic"] == []
