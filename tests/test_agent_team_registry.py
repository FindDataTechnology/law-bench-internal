"""岗位注册表：参数属于线，机制属于内核。

三件事：

- pack 里的 `roles` 段是唯一参数来源，内核不认识任何行业；
- 未知岗位名 / 未知参数 / 类型不对一律报错，不静默忽略（拼写错误是最难查的配置事故）；
- 未声明的线不启动，并说清"未声明"，不套用别的线的默认值。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401 — 注册归名规则（与 web 边缘一致）
from src.bench import agent_team, packs

BASE = {
    "name": "demo",
    "version": "0.1.0",
    "description": "d",
    "kinds": ["clause"],
    "components": [],
    "eval_suites": [],
}


def _manifest(**roles):
    return {**BASE, "roles": roles}


# ── 词表与参数校验 ──────────────────────────────────────────────────────────


def test_role_vocabulary_is_closed():
    assert set(agent_team.ROLES) == {
        "scout", "builder", "concept", "verifier", "eval", "release", "warden"
    }


def test_unknown_role_is_refused():
    with pytest.raises(agent_team.RoleDeclarationError, match="未知岗位"):
        agent_team.declared_roles(_manifest(consept={"enabled": True}), pack_name="demo")


def test_unknown_param_is_refused():
    """拼错的参数名必须报错，否则它会被静默忽略、跑成默认行为。"""
    with pytest.raises(agent_team.RoleDeclarationError, match="未知参数"):
        agent_team.declared_roles(
            _manifest(concept={"enabled": True, "batch_chunk": 10}), pack_name="demo")


def test_types_are_checked():
    with pytest.raises(agent_team.RoleDeclarationError, match="enabled"):
        agent_team.declared_roles(_manifest(warden={"enabled": "yes"}), pack_name="demo")
    with pytest.raises(agent_team.RoleDeclarationError, match="cadence_minutes"):
        agent_team.declared_roles(_manifest(warden={"cadence_minutes": 0}), pack_name="demo")


def test_roles_must_be_a_mapping():
    with pytest.raises(agent_team.RoleDeclarationError, match="必须是映射"):
        agent_team.declared_roles({**BASE, "roles": ["warden"]}, pack_name="demo")


def test_absent_roles_section_is_empty_not_an_error():
    assert agent_team.declared_roles(BASE) == {}


# ── 两条真实线 ──────────────────────────────────────────────────────────────


def test_legal_declares_readonly_and_write_roles():
    plan = agent_team.plan("legal")
    roles = {r["role"]: r for r in plan["runnable"]}
    assert plan["declared"] is True
    assert roles["warden"]["cadence_minutes"] == 15
    assert roles["concept"]["params"]["batch_chunks"] == 10
    # 未声明的岗位不起——eval / release 在 legal 里没有声明
    assert "eval" in plan["skipped"] and "release" in plan["skipped"]


def test_gov_declares_its_own_parameters():
    plan = agent_team.plan("gov")
    roles = {r["role"]: r for r in plan["runnable"]}
    assert plan["declared"] is True
    # 政务线的文种与法律线不同，参数各自声明，互不影响
    assert "办法" in roles["scout"]["params"]["doc_types"]
    assert "concept" in plan["skipped"]


def test_write_roles_have_no_default_cadence():
    """写类的节奏是业务决定；没声明就是 None，不替它猜一个数字。"""
    assert agent_team.cadence_minutes("concept", {}) is None
    assert agent_team.cadence_minutes("warden", {}) == 15


# ── 未声明的线 ──────────────────────────────────────────────────────────────


def test_an_undeclared_line_does_not_start(monkeypatch):
    plan = agent_team.plan("no-such-line")
    assert plan["declared"] is False
    assert plan["runnable"] == []
    assert "未声明" in plan["reason"]


def test_a_pack_without_roles_does_not_start(monkeypatch):
    monkeypatch.setattr(packs, "load_pack", lambda name: dict(BASE))
    plan = agent_team.plan("demo")
    assert plan["declared"] is False
    assert "没有 roles 段" in plan["reason"]


def test_plan_never_writes(monkeypatch):
    """计划是纯读：编排层刷新一次不该变成一次配置变更。"""
    calls = []
    monkeypatch.setattr(packs, "load_pack",
                        lambda name: calls.append(name) or dict(_manifest(warden={})))
    agent_team.plan("demo")
    assert calls == ["demo"]


def test_validate_pack_catches_a_bad_roles_section():
    problems = packs.validate_pack(_manifest(warden={"enabled": "yes"}))
    assert any("enabled" in p for p in problems)


def test_validate_pack_accepts_the_real_packs():
    for name in ("legal", "gov"):
        manifest = packs.load_pack(name)
        assert packs.validate_pack(manifest, directory=name) == []
