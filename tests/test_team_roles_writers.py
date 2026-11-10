"""确定性写岗位：取材员与结构员。

这两个岗位有写权限，所以验收比只读岗硬：

- **幂等**：同一输入跑两遍，第二遍零新增（不是"少新增"）；
- **只在本域已订阅的范围内取材**，不放宽订阅；
- **文种筛选生效与否要如实说**：来源给不出文种就报"未按文种筛选"并判 `thin`，
  不能假装筛过；
- **结构员只补"还一条条款都没有"的文档**，不每轮重扫；
- 失败仍留台账（回滚后再写）。
"""

from __future__ import annotations

import httpx
import pytest

import packs.legal  # noqa: F401
from src.bench import (agent_runs, authoring, corpus_catalog, libraries, team_roles,
                       templates, workspaces)
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.search import library_index

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": ["external"]},
}

MAPPING = {"id": "doc_key", "title": "doc_title", "text": "body", "order": "seq",
           "kind": "doc_kind", "unit_kind": "law", "clause_kind": "clause"}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # 评测柱会读 rubrics；它来自遗留 seed，不在 ensure_schema 里
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT, "
        "description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    lib = libraries.create_library(
        conn=empty_db, library_key="law-library", name="law-library", created_by="t",
        backend="qdrant", embedding_model="m", dims=1024,
        location={"url_env": "TEST_QDRANT_URL", "collection": "corpus"})
    libraries.add_source(
        conn=empty_db, library_key="law-library", source_key="statutes",
        uri="collection:corpus/statutes", created_by="t", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["statutes"]}, "document": MAPPING})
    dom = empty_db.execute("SELECT id FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn=empty_db, domain_id=dom["id"], library_key="law-library",
                        created_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


class _FakeQdrant:
    """按 {doc_id: (title, kind, [chunks])} 回答 facet/scroll。"""

    def __init__(self, docs):
        self.docs = docs

    def __call__(self, url, *, json=None, headers=None, timeout=None):  # noqa: A002
        body = json or {}
        if url.endswith("/facet"):
            hits = [{"value": k, "count": len(v[2])} for k, v in self.docs.items()]
            payload = {"result": {"hits": hits}}
        else:
            must = (body.get("filter") or {}).get("must") or []
            clause = next((c for c in must if c["key"] == "doc_key"), {})
            match = clause.get("match") or {}
            ids = ([str(v) for v in match["any"]] if "any" in match
                   else [str(match["value"])] if "value" in match else list(self.docs))
            points = []
            for doc_id in ids:
                title, kind, chunks = self.docs[doc_id]
                for i, text in enumerate(chunks):
                    if "any" in match and i != 0:
                        continue
                    points.append({"id": f"{doc_id}-{i}", "payload": {
                        "doc_key": doc_id, "doc_title": title, "body": text,
                        "seq": i, "doc_kind": kind}})
            payload = {"result": {"points": points[: int(body.get("limit") or 100)]}}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


@pytest.fixture()
def fake(monkeypatch):
    def install(docs):
        monkeypatch.setattr(library_index, "_http_post", _FakeQdrant(docs))
        monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")

    return install


DOCS = {
    "7": ("中华人民共和国合同法", "法律", ["第一条 甲。\n第二条 乙。"]),
    "9": ("中华人民共和国公司法", "法律", ["第一条 丙。"]),
}


# ── 取材员 ──────────────────────────────────────────────────────────────────


def test_scout_adopts_documents_and_folds_their_keys(conn, fake):
    fake(DOCS)
    out = team_roles.run_scout(conn, domain_key="legal")
    assert out["adopted"] == 2
    keys = {r["external_key"] for r in conn.execute(
        "SELECT external_key FROM knowledge_units WHERE kind='law'").fetchall()}
    assert keys == {"合同法", "公司法"}, "文件键应已按域规则归名"


def test_scout_is_idempotent(conn, fake):
    fake(DOCS)
    team_roles.run_scout(conn, domain_key="legal")
    second = team_roles.run_scout(conn, domain_key="legal")
    assert second["adopted"] == 0, "同输入重跑必须零新增"


def test_scout_filters_by_declared_doc_types(conn, fake):
    fake(DOCS)
    out = team_roles.run_scout(conn, domain_key="legal")
    # legal 的 pack 声明 scout.doc_types 含 法律，两份都该入选
    assert out["skipped_kind"] == 0


def test_scout_reports_when_doc_types_could_not_be_applied(conn, fake, monkeypatch):
    """来源给不出文种时必须说"未筛"，并判 thin——不能假装筛过。

    直接替换 _role_params：这个测试要钉的是 run_scout 在"声明了文种但来源给不出"
    时的行为，不该依赖 legal 的 pack 是否恰好声明了 doc_types（那是别的测试的事）。
    """
    fake({k: (t, None, c) for k, (t, _kind, c) in DOCS.items()})
    monkeypatch.setattr(team_roles, "_role_params",
                        lambda d, r: {"doc_types": ["法律"], "sources": ["statutes"], "limit": 10})
    out = team_roles.run_scout(conn, domain_key="legal")
    assert any("未按文种筛选" in w for w in out["warnings"])
    assert out["run"]["outcome"] == "thin"


def test_scout_does_not_widen_the_subscription(conn, fake):
    fake(DOCS)
    before = libraries.effective_sources(conn, domain_path="legal")
    team_roles.run_scout(conn, domain_key="legal")
    after = libraries.effective_sources(conn, domain_path="legal")
    assert before == after


# ── 结构员 ──────────────────────────────────────────────────────────────────


def test_builder_adds_articles_to_adopted_documents(conn, fake):
    fake(DOCS)
    team_roles.run_scout(conn, domain_key="legal")
    out = team_roles.run_builder(conn, domain_key="legal")
    assert out["built"] == 2
    keys = {r["external_key"] for r in conn.execute(
        "SELECT external_key FROM knowledge_units WHERE kind='clause'").fetchall()}
    assert "合同法#第1条" in keys and "公司法#第1条" in keys


def test_builder_does_not_rescan_documents_that_already_have_articles(conn, fake):
    fake(DOCS)
    team_roles.run_scout(conn, domain_key="legal")
    team_roles.run_builder(conn, domain_key="legal")
    second = team_roles.run_builder(conn, domain_key="legal")
    assert second["built"] == 0
    assert second["already_had_clauses"] == 2


def test_builder_says_why_it_skipped_a_document(conn, fake, monkeypatch):
    """来源没声明 clause_kind 时，结构员要说明原因而不是静默跳过。"""
    fake(DOCS)
    team_roles.run_scout(conn, domain_key="legal")
    src = conn.execute(
        "SELECT id, ingest_rule FROM library_sources WHERE source_key='statutes'").fetchone()
    rule = dict(src["ingest_rule"])
    rule["document"] = {k: v for k, v in MAPPING.items() if k != "clause_kind"}
    conn.execute("UPDATE library_sources SET ingest_rule = %s::jsonb WHERE id = %s",
                 (__import__("json").dumps(rule), src["id"]))
    conn.commit()
    out = team_roles.run_builder(conn, domain_key="legal")
    assert out["built"] == 0
    assert any("clause_kind" in s["reason"] for s in out["skips"])


# ── 台账 ────────────────────────────────────────────────────────────────────


def test_both_writers_leave_ledger_rows(conn, fake):
    fake(DOCS)
    team_roles.run_scout(conn, domain_key="legal")
    team_roles.run_builder(conn, domain_key="legal")
    roles = {r["role"] for r in agent_runs.list_runs(conn, domain_key="legal")}
    assert {"agent:scout@legal", "agent:builder@legal"} <= roles


def test_a_writer_failure_is_recorded(conn, fake, monkeypatch):
    fake(DOCS)

    def boom(*a, **kw):
        raise RuntimeError("目录读不了")

    monkeypatch.setattr(team_roles.corpus_catalog, "documents", boom)
    with pytest.raises(RuntimeError):
        team_roles.run_scout(conn, domain_key="legal")
    rows = agent_runs.list_runs(conn, domain_key="legal", role="agent:scout@legal")
    assert rows and rows[0]["outcome"] == "failed"
    assert "目录读不了" in (rows[0]["detail"] or "")
