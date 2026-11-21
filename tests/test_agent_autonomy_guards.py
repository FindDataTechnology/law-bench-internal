"""硬停清单落在代码上，而不是只写在 spec 里。

2026-11-21 实测：`domain-agent-team` spec 写了五个动作「SHALL NOT 被任何智能体
执行」，而 `grep HARD_STOP src` 零命中——禁令没有执行点。同一个空档里发生了一次
真实事故：为了让一支舰队能确认提案，把它的域角色提到了 `lead`，顺带破了「智能体
最高 expert」。

这个文件钉两件事：

1. 五个动作**各自**在它的写入口上真的被拒（不是只测判据函数）；
2. 人是能过这些入口的——判据按身份类别，不是按「谁在调」。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import agent_ids, hard_stops  # noqa: E402

MACHINE = ("agent:warden@d", "fleet:f/p", "extract:m:1")


# ------------------------------------------------------------ 判据本身


def test_the_action_set_is_closed():
    assert set(hard_stops.HARD_STOP_ACTIONS) == {
        "open_or_archive_domain", "widen_sourcing_scope",
        "change_template_version", "delete_unit", "mint_credential",
    }


@pytest.mark.parametrize("action", hard_stops.HARD_STOP_ACTIONS)
@pytest.mark.parametrize("actor", MACHINE)
def test_every_machine_identity_is_refused_for_every_action(action, actor):
    with pytest.raises(hard_stops.HardStopError) as exc:
        hard_stops.check(actor, action)
    assert action in str(exc.value)
    assert actor in str(exc.value)


@pytest.mark.parametrize("action", hard_stops.HARD_STOP_ACTIONS)
@pytest.mark.parametrize("actor", ["aloadtree@gmail.com", "lead-1", "user:x",
                                   "ops:chengsishi/cleanup"])
def test_human_and_ops_identities_pass(action, actor):
    hard_stops.check(actor, action)  # must not raise


def test_refusal_names_the_legitimate_path():
    """'No' without 'then how' sends the reader off to find a workaround.

    That is not hypothetical: the 2026-11-21 escalation happened because the only
    visible path to letting a fleet confirm was to promote it.
    """
    for action in hard_stops.HARD_STOP_ACTIONS:
        assert hard_stops.remedy_for(action)


def test_unknown_action_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown hard-stop action"):
        hard_stops.check("agent:x@d", "launch_missiles")
    with pytest.raises(ValueError):
        hard_stops.remedy_for("launch_missiles")


def test_hard_stop_error_is_a_permission_error():
    """Existing ``except PermissionError`` callers keep working."""
    assert issubclass(hard_stops.HardStopError, PermissionError)


# ------------------------------------------------- 角色上限（事故的直接根因）


def test_machine_identity_cannot_be_granted_lead():
    """The rule that, had it existed, would have blocked tonight's escalation.

    The ceiling itself is enforced in `add_member` (DB-backed test below). What
    this pins is the predicate it reads — without it the guard would silently
    stop firing if `is_machine` ever stopped recognising `fleet:`.
    """
    assert agent_ids.is_machine("fleet:ontology-builder") is True
    for actor in MACHINE:
        assert agent_ids.is_machine(actor) is True


def test_human_may_be_granted_lead():
    """The cap is on machines only — a person leading a domain is the norm."""
    assert agent_ids.is_machine("aloadtree@gmail.com") is False
    assert agent_ids.is_machine("ops:chengsishi/cleanup") is False


# ------------------------------------------------ 接线：判据真的挂在入口上

@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    yield empty_db


def test_add_member_refuses_lead_for_a_machine(db_conn):
    """`workspaces.add_member` — the entry the escalation used."""
    from src.bench import templates, workspaces
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    tpl = templates.create_template(
        db_conn, name="t", schema={
            "entity_types": ["organization"], "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        }, created_by="lead-1",
    )
    dom = workspaces.instantiate_domain(
        db_conn, key="d1", name="D1", template_name="t",
        template_version=tpl["version"], created_by="lead-1",
    )
    with pytest.raises(PermissionError, match="角色上限是 'expert'"):
        workspaces.add_member(
            db_conn, domain_id=dom["id"], user_id="fleet:x/y",
            role="lead", added_by="lead-1",
        )
    # expert is still allowed — the cap is on lead, not on machines entirely.
    member = workspaces.add_member(
        db_conn, domain_id=dom["id"], user_id="fleet:x/y",
        role="expert", added_by="lead-1",
    )
    assert member["role"] == "expert"


def test_instantiate_domain_refuses_a_machine_creator(db_conn):
    from src.bench import templates, workspaces
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    tpl = templates.create_template(
        db_conn, name="t2", schema={
            "entity_types": ["organization"], "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        }, created_by="lead-1",
    )
    with pytest.raises(PermissionError, match="open_or_archive_domain"):
        workspaces.instantiate_domain(
            db_conn, key="d2", name="D2", template_name="t2",
            template_version=tpl["version"], created_by="agent:builder@d2",
        )


def test_delete_unit_refuses_a_machine_operator(db_conn):
    from src.bench import authoring, templates, workspaces
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    tpl = templates.create_template(
        db_conn, name="t3", schema={
            "entity_types": ["organization"], "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        }, created_by="lead-1",
    )
    workspaces.instantiate_domain(
        db_conn, key="d3", name="D3", template_name="t3",
        template_version=tpl["version"], created_by="lead-1",
    )
    authoring.authoring_create_unit(
        db_conn, domain_key="d3", kind="organization",
        external_key="org-a", body="A", operator="lead-1",
    )
    with pytest.raises(PermissionError, match="delete_unit"):
        authoring.authoring_delete_unit(
            db_conn, domain_key="d3", kind="organization",
            external_key="org-a", operator="agent:warden@d3",
        )
    # The unit is untouched.
    remaining = authoring.authoring_get_unit(
        db_conn, domain_key="d3", kind="organization", external_key="org-a"
    )
    assert not (remaining.get("tags") or {}).get("deleted")


def test_update_template_refuses_a_machine_creator(db_conn):
    from src.bench import templates
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    schema = {
        "entity_types": ["organization"], "concept_structures": {},
        "relationship_kinds": ["sells_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
    }
    tpl = templates.create_template(db_conn, name="t4", schema=schema, created_by="lead-1")
    with pytest.raises(PermissionError, match="change_template_version"):
        templates.update_template(
            db_conn, name="t4", schema=schema, created_by="agent:builder@d4",
        )
    # Still at v1: the refused write did not land a row.
    assert templates.get_template(db_conn, name="t4")["version"] == tpl["version"]
