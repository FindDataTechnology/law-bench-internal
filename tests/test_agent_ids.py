"""机器身份口径的守门测试（``src/bench/agent_ids.py``）。

这个模块存在的前提是：**「谁是机器」只能有一份口径**。所以这里钉两件事：

1. ``is_machine`` 覆盖所有机器类别前缀，不只是 ``agent:``；
2. 它的词表与 :mod:`src.bench.submitters` 的 ``PREFIX_*`` 一致——两处各写一遍迟早漂移，
   一处改了另一处还认旧写法，闸门就静默失效（2026-11-14 正是这么漏的：
   ``confirm`` 只判 ``agent:``，于是 ``fleet:probe`` 能当签字人）。
"""

from __future__ import annotations

import pytest

from src.bench import agent_ids, submitters


def test_machine_prefixes_match_the_submitter_vocabulary():
    """别在 ``MACHINE_PREFIXES`` 里手加前缀而不改这里：那正是漂移。"""
    expected = {
        submitters.PREFIX_AGENT,
        submitters.PREFIX_FLEET,
        submitters.PREFIX_EXTRACT,
    }
    assert set(agent_ids.MACHINE_PREFIXES) == expected


@pytest.mark.parametrize(
    "identity",
    [
        "agent:concept@legal",   # 岗位
        "fleet:probe",           # 舰队（2026-11-14 就是这么签上字的）
        "fleet:fleet_1794335712751_wfa3ww/post_acceptance",
        "extract:deepseek-v4.1-flash:2026-11-09.1",
        "  fleet:probe  ",       # 带空白也要认
    ],
)
def test_machine_identities_are_recognised(identity):
    assert agent_ids.is_machine(identity) is True


@pytest.mark.parametrize(
    "identity",
    [
        "lead-1",
        "dev@local",
        "aloadtree@gmail.com",
        "user:zhangsan",
        "",
        None,
    ],
)
def test_human_identities_are_not_machine(identity):
    assert agent_ids.is_machine(identity) is False


def test_is_agent_stays_narrow():
    """``is_agent`` 仍只认 ``agent:``：铸凭据那道闸的语义没变。"""
    assert agent_ids.is_agent("agent:x@y") is True
    assert agent_ids.is_agent("fleet:probe") is False


# ------------------------------------------------------------ 运维裁决身份


def test_ops_identity_is_not_a_machine_identity():
    """Ops decisions are made by people; classifying them as machine would
    forbid the very action they exist to authorise."""
    assert agent_ids.is_ops("ops:chengsishi/dup-keys") is True
    assert agent_ids.is_machine("ops:chengsishi/dup-keys") is False


@pytest.mark.parametrize(
    "identity",
    ["ops:", "ops:chengsishi", "ops:/reason", "ops:a/b/c", "ops:has space/x",
     "ops:x/y\tz", "", None, "system:import", "fleet:probe", "user:alice"],
)
def test_ops_identity_shape_is_enforced(identity):
    """`<operator>/<reason>` with both parts non-empty and no extra separator."""
    assert agent_ids.is_ops(identity) is False


def test_ops_identity_builder_round_trips():
    built = agent_ids.ops_identity("chengsishi", "duplicate-submissions")
    assert built == "ops:chengsishi/duplicate-submissions"
    assert agent_ids.is_ops(built) is True


@pytest.mark.parametrize("operator,reason", [("", "r"), ("o", ""), ("a b", "r"),
                                             ("o", "a/b")])
def test_ops_identity_builder_refuses_incomplete_parts(operator, reason):
    with pytest.raises(ValueError):
        agent_ids.ops_identity(operator, reason)
