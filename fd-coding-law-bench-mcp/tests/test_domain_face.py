"""Tests for the domain-face tools (change ``domain-first-mcp``).

These pin the three properties that make the face safe to expose to a model:

- **domain is required** — a call with no domain is refused, never defaulted;
- **unknown ≠ empty** — a domain the caller cannot see raises, because an empty
  list reads as "this domain has nothing", which is a different (false) claim;
- **read-only** — no tool in the face writes.

Hermetic: the kernel (``src.bench``) is monkeypatched; the shared DB connect is
a stub, so no database is touched.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _Conn:
    """Stands in for a psycopg connection: ``close`` plus an ``execute`` that
    returns no rows (``domain_context`` asks for per-kind counts)."""

    def close(self) -> None:  # noqa: D401 - stub
        pass

    def execute(self, *a, **kw):
        class _Cur:
            @staticmethod
            def fetchall():
                return []
        return _Cur()


@pytest.fixture(autouse=True)
def _stub_connect(monkeypatch):
    import src.eval.db as db

    monkeypatch.setattr(db, "connect", lambda: _Conn())


def _patch_kernel(monkeypatch, *, domain_row, units=None, actions=None,
                  pending=0, proposals=None, role="expert"):
    """Install a fake ``src.bench`` kernel with the given behaviour."""
    import src.bench as bench_pkg

    class FakeWS:
        ROLE_RANK = {"annotator": 0, "expert": 1, "lead": 2}

        @staticmethod
        def get_domain(conn, *, domain_key=None, domain_id=None):
            return domain_row

        @staticmethod
        def list_domains(conn, *, user_id=None, include_archived=False):
            return [domain_row] if domain_row else []

        @staticmethod
        def get_active_role(conn, *, domain_id, user_id):
            return role

    class FakeStore:
        @staticmethod
        def list_knowledge_units(conn, **kw):
            return units or []

        @staticmethod
        def get_knowledge_unit(conn, *, kind, external_key, namespace):
            for u in units or []:
                if u["kind"] == kind and u["external_key"] == external_key:
                    return u
            return None

    class FakeActions:
        @staticmethod
        def for_domain(conn, domain, *, probed=None):
            return actions or {"ranked": {"top": [], "more": 0, "total": 0}}

    class FakeProposals:
        @staticmethod
        def count_pending(conn, *, domain_key):
            return pending

        @staticmethod
        def list_proposals(conn, *, domain_key, state=None, batch=None, limit=200):
            return proposals or []

        @staticmethod
        def get(conn, *, domain_key, proposal_id):
            return None

        @staticmethod
        def events_for(conn, *, proposal_id):
            return []

    class FakeChecks:
        @staticmethod
        def checks_for_unit(unit):
            return [{"name": "body-present", "passed": True, "detail": "ok"}]

        @staticmethod
        def summarise(checks):
            return {"checkable": True, "passed": 1, "total": 1,
                    "all_pass": True, "failed_names": []}

    for name, fake in (
        ("workspaces", FakeWS), ("store", FakeStore), ("next_actions", FakeActions),
        ("proposals", FakeProposals), ("unit_checks", FakeChecks),
    ):
        monkeypatch.setattr(bench_pkg, name, fake, raising=False)


_DOMAIN = {"id": 4, "key": "dt", "name": "数据本体域", "path": "dt",
           "parent_key": None}


async def test_domain_is_required_and_never_defaulted(monkeypatch):
    """没有域就拒，不退化到「默认域」。"""
    _patch_kernel(monkeypatch, domain_row=_DOMAIN)
    from fd_coding_law_bench_mcp.tools.domain import domain_units

    with pytest.raises(ValueError, match="domain is required"):
        await domain_units(domain="")


async def test_unknown_domain_raises_rather_than_returning_empty(monkeypatch):
    """未知域 = 报错。「空列表」会被读成「这个域没有内容」，那是另一种（假的）说法。"""
    _patch_kernel(monkeypatch, domain_row=None)
    from fd_coding_law_bench_mcp.tools.domain import domain_units

    with pytest.raises(ValueError, match="unknown domain"):
        await domain_units(domain="no-such-domain")


async def test_domain_units_filters_by_the_given_domain(monkeypatch):
    """域是查询条件，不是提示词——它必须落到 namespace 上。"""
    seen = {}

    def fake_list(conn, **kw):
        seen.update(kw)
        return [{"external_key": "k1", "kind": "clause", "tier": "raw",
                 "body": "正文", "updated_at": None}]

    _patch_kernel(monkeypatch, domain_row=_DOMAIN)
    import src.bench as bench_pkg

    class S:
        list_knowledge_units = staticmethod(fake_list)
    monkeypatch.setattr(bench_pkg, "store", S, raising=False)

    from fd_coding_law_bench_mcp.tools.domain import domain_units

    out = await domain_units(domain="dt", kind="clause")
    assert seen["namespace"] == "dt", f"域没有落到 namespace 上：{seen}"
    assert out[0]["external_key"] == "k1"


async def test_domain_context_uses_the_same_projection_as_the_page(monkeypatch):
    """下一动作来自 next_actions.for_domain，不在工具里重算。"""
    _patch_kernel(
        monkeypatch, domain_row=_DOMAIN, pending=3,
        actions={"ranked": {"top": [{"action": "批一批提案", "reason": "3 条待确认",
                                     "entry": "/d/dt/inbox", "priority_key": "inbox"}],
                            "more": 0, "total": 1}},
    )
    from fd_coding_law_bench_mcp.tools.domain import domain_context

    ctx = await domain_context(domain="dt")
    assert ctx["domain"] == "dt"
    assert ctx["next_actions"][0]["action"] == "批一批提案"
    assert ctx["pending_proposals"] == 3


async def test_ruler_list_is_domain_scoped(monkeypatch):
    """尺子按域解析（effective_rubrics 拿到的是该域的 path）。"""
    import src.bench as bench_pkg
    seen = {}

    class DR:
        @staticmethod
        def effective_rubrics(conn, *, domain_path):
            seen["path"] = domain_path
            return [{"id": 1, "name": "r1", "context": "check", "source": "local",
                     "domain_id": 4, "derived_from": None, "fork_diff": None}]

    monkeypatch.setattr(bench_pkg, "domain_rubrics", DR, raising=False)
    _patch_kernel(monkeypatch, domain_row=_DOMAIN)

    from fd_coding_law_bench_mcp.tools.rulers import ruler_list

    out = await ruler_list(domain="dt")
    assert seen["path"] == "dt"
    assert out[0]["name"] == "r1"


async def test_domain_face_write_surface_is_exactly_two_tools():
    """域面写面是**闭集**：只有确认提案与升一格。

    这条是结构性约束，不是语气：新增任何写工具都会让它红，从而逼人回来读一遍
    「哪些动作机器可以合法做」。当前的两个都来自内核已有的裁决（2026-11-21：
    权力来源是档位而非身份形状；机器确认产出 silver，gold 仍须人）。
    """
    import sys
    sys.path.insert(0, "fd-coding-law-bench-mcp/src")
    import fd_coding_law_bench_mcp.server as server

    tools = await server.mcp._list_tools()
    domain_face = [t for t in tools if t.name.startswith(("domain_", "ruler_"))]
    assert len(domain_face) >= 10, [t.name for t in domain_face]
    write_verbs = ("promote", "publish", "confirm", "reject", "create", "update",
                   "delete", "apply", "store", "submit")
    writers = sorted(t.name for t in domain_face if any(v in t.name for v in write_verbs))
    assert writers == ["domain_proposal_confirm", "domain_unit_promote"], (
        f"域面写面变了：{writers}。若这是有意的，先确认那个动作机器有权做，"
        "再改这条断言。"
    )

async def test_write_tools_refuse_a_non_lead(monkeypatch):
    """非 lead 不能签字。`actor` 是调用方自报的字符串，所以必须回库核一遍。"""
    _patch_kernel(monkeypatch, domain_row=_DOMAIN, role="expert")
    from fd_coding_law_bench_mcp.tools.domain_write import (
        domain_proposal_confirm, domain_unit_promote,
    )

    with pytest.raises(PermissionError, match="requires 'lead'"):
        await domain_proposal_confirm(domain="dt", proposal_id=1, actor="someone@x")
    with pytest.raises(PermissionError, match="requires 'lead'"):
        await domain_unit_promote(domain="dt", kind="clause",
                                  external_key="k1", actor="someone@x")


async def test_write_tools_refuse_a_non_member(monkeypatch):
    """不在域里的人，连签字资格都没有。"""
    _patch_kernel(monkeypatch, domain_row=_DOMAIN, role=None)
    from fd_coding_law_bench_mcp.tools.domain_write import domain_proposal_confirm

    with pytest.raises(PermissionError, match="no active membership"):
        await domain_proposal_confirm(domain="dt", proposal_id=1, actor="stranger@x")


async def test_write_tool_requires_an_actor(monkeypatch):
    """签字必须带身份；空 actor 直接拒，不猜「当前用户」。"""
    _patch_kernel(monkeypatch, domain_row=_DOMAIN)
    from fd_coding_law_bench_mcp.tools.domain_write import domain_proposal_confirm

    with pytest.raises(ValueError, match="actor is required"):
        await domain_proposal_confirm(domain="dt", proposal_id=1, actor="  ")


async def test_promote_stops_at_gold(monkeypatch):
    """gold 这条路在域面被有意封死：机器没有人工复核身份可签。

    内核要求 gold 必须带 reviewer；机器若拿自己的名字当 reviewer，就是在伪造
    一条人工核验记录——那正是 tiers 守卫存在的理由。
    """
    _patch_kernel(monkeypatch, domain_row=_DOMAIN, role="lead")
    import src.bench as bench_pkg

    class P:
        CHAIN = ("raw", "silver", "gold")
        SYNC_TIER = "bronze"

        @staticmethod
        def _get_unit(conn, *, kind, external_key, namespace):
            return {"kind": kind, "external_key": external_key,
                    "tier": "silver", "tags": {}, "provenance": {}}

    monkeypatch.setattr(bench_pkg, "promotion", P, raising=False)
    from fd_coding_law_bench_mcp.tools.domain_write import domain_unit_promote

    with pytest.raises(PermissionError, match="human reviewer"):
        await domain_unit_promote(domain="dt", kind="clause",
                                  external_key="k1", actor="lead@x")
