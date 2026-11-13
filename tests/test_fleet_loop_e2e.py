"""一条闭环，全程走真实 HTTP（add-fleet-execution-loop §7.1 / §6.4 的离线那半）。

审定过的判据是「缺口 → 工单 → 舰队认领 → 执行 → 运行回写 → 产物入箱 → 确认 → 结果
可见」。这条测试就走这一串，**不调内核函数**（除了造世界）：任何一处接线缺失，链路
就断在一个具体的状态码上。

为什么值得写成一整条而不是八个单测：每一段单独绿的时候，缝里可能根本没接上——工单
派得出去但没人能认领、回写落库了但读不回来、提案进了箱但确认路径不认这个来源。这些
都只在**串联**的时候才现形。

身份：舰队用 `X-Consumer-Token`（机器，无会话），域负责人用会话身份。两者是不同的
闸，混用就等于没测。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import distribution, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

DOMAIN = "loop-domain"
TOKEN = "loop-fleet-token"
FLEET_REF = "fleet_loop"


@pytest.fixture()
def world(seeded_db):  # noqa: F811 - provided by tests/conftest.py
    conn = seeded_db
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn, name="loop-tpl", schema=schema, created_by="seed")
    domain = workspaces.instantiate_domain(
        conn, key=DOMAIN, name="闭环域", template_name="loop-tpl",
        template_version=None, created_by="seed",
    )
    workspaces.add_member(
        conn, domain_id=domain["id"], user_id="lara", role="lead", added_by="seed"
    )
    # 舰队这一侧是**服务身份**（不是 lara）：提交与复核必须两个人，否则自提自确认
    # 闸会（正确地）拦下确认，闭环就走不完。
    workspaces.add_member(
        conn, domain_id=domain["id"], user_id="svc-fleet", role="expert", added_by="seed"
    )
    distribution.register_consumer(
        conn, name="loop-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(), created_by="seed",
        kind="fleet", fleet_ref=FLEET_REF,
    )
    yield conn


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _machine(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _human(db, sub: str = "lara") -> TestClient:
    app = create_app()
    user = User(sub=sub, name=sub, email=f"{sub}@example.com",
                scopes=["content:read", "content:write"], channel="test")

    def _current(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current
    return TestClient(app)


def _machine_headers():
    return {"X-Consumer-Token": TOKEN}


def test_the_whole_loop_over_http(world):
    conn = world

    # ① 缺口存在：本域还没有自己的知识单元（estate 判据与派单同源）。
    from src.bench import dispatch, estate

    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    rows = estate.matrix(conn, domains=[domain])
    assert "ontology" in rows[0]["gaps"], "闭环应从「真的有缺口」开始"

    # ② 派单给舰队（会话身份：lead）。走真实表单端点。
    with _human(conn) as h:
        dispatched = h.post(
            "/d/dispatch",
            data={
                "gap": "ontology", "assignee": "loop-fleet",
                "assignee_kind": "fleet", "assignee_ref": FLEET_REF,
            },
            follow_redirects=False,
        )
    assert dispatched.status_code == 303, dispatched.text

    task = conn.execute(
        "SELECT id, assignee_kind, assignee_ref, status FROM authoring_tasks "
        "WHERE target_key = 'ontology'"
    ).fetchone()
    assert (task["assignee_kind"], task["assignee_ref"], task["status"]) == (
        "fleet", FLEET_REF, "pending",
    )

    # ③ 舰队领单（机器身份，无会话）。别人认领不了它。
    with _machine(conn) as m:
        claimed = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers=_machine_headers(),
        )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["task"]["status"] == "in_progress"

    with _machine(conn) as m:
        again = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers=_machine_headers(),
        )
    assert again.status_code == 409, "重复认领必须被拒，而不是静默成功"

    # ④ 执行完回写这一轮（机器身份，幂等）。
    runner_ref = f"fleet:{FLEET_REF}/post_ontology#1"
    with _machine(conn) as m:
        wrote = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={
                "runner_ref": runner_ref, "role": "concept", "outcome": "ok",
                "counts": {"drafts": 2}, "task_id": task["id"],
            },
            headers=_machine_headers(),
        )
    assert wrote.status_code == 200, wrote.text
    assert wrote.json()["created"] is True

    with _machine(conn) as m:
        replay = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": runner_ref, "role": "concept", "outcome": "failed"},
            headers=_machine_headers(),
        )
        readback = m.get(
            f"/api/v1/distribution/{DOMAIN}/runs",
            params={"runner_ref": runner_ref}, headers=_machine_headers(),
        )
    assert replay.json()["created"] is False
    assert replay.json()["run"]["outcome"] == "ok", "重放不得改写已记录的结局"
    assert readback.json()["count"] == 1

    # ⑤ 产物入箱（舰队来源，经登记校验）。提交用舰队侧的服务身份。
    with _human(conn, "svc-fleet") as h:
        submitted = h.post(
            f"/api/d/{DOMAIN}/proposals",
            json={
                "source": f"fleet:{FLEET_REF}/post_ontology",
                "kind": "company", "external_key": "loop-corp",
                "body": "闭环域的第一家主体", "evidence": {"url": "https://e.test/1"},
            },
        )
    assert submitted.status_code == 200, submitted.text

    # ⑥ 域负责人确认 → 知识单元落库。
    with _human(conn) as h:
        confirmed = h.post(
            f"/d/{DOMAIN}/inbox/{submitted.json()['id']}/confirm",
            follow_redirects=False,
        )
    assert confirmed.status_code == 303, confirmed.text
    assert "err=1" not in confirmed.headers["location"], confirmed.headers["location"]

    unit = conn.execute(
        "SELECT count(*) AS n FROM knowledge_units WHERE external_key = 'loop-corp'"
    ).fetchone()
    assert unit["n"] == 1, "确认后单元必须真的出现在库里"

    # ⑦ 缺口消失 + 结果对提交方可见（同一个域，四份证据都在）。
    rows_after = estate.matrix(conn, domains=[workspaces.get_domain(conn, domain_key=DOMAIN)])
    assert "ontology" not in rows_after[0]["gaps"], "闭环走完，缺口应当消失"

    with _human(conn) as h:
        outcomes = h.get(
            f"/api/d/{DOMAIN}/proposals/outcomes",
            params={"source": f"fleet:{FLEET_REF}/post_ontology"},
        )
    assert outcomes.status_code == 200, outcomes.text
    assert outcomes.json()["outcomes"][0]["state"] == "confirmed"

    # ⑧ 舰队关单（机器身份）。
    with _machine(conn) as m:
        done = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            json={"note": "产出 2 条草案", "artifact_refs": [{"proposal_id": submitted.json()["id"]}]},
            headers=_machine_headers(),
        )
    assert done.status_code == 200, done.text
    assert done.json()["task"]["status"] == "done"

    # 四份证据一起核对：工单、运行、提案、单元。
    assert conn.execute(
        "SELECT count(*) AS n FROM authoring_tasks WHERE status = 'done'"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE runner_ref = %s", (runner_ref,)
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM domain_proposals WHERE state = 'confirmed'"
    ).fetchone()["n"] == 1


def test_another_fleet_cannot_claim_or_close_the_task(world):
    """派给 A 的工单，B 认领不了；显示名相同也不行——授权读的是登记引用。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    distribution.register_consumer(
        conn, name="other-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"other").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_other",
    )
    with _machine(conn) as m:
        stolen = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers={"X-Consumer-Token": "other"},
        )
    assert stolen.status_code == 403
    assert "不是派给舰队" in stolen.json()["detail"]


def test_the_machine_surface_still_refuses_a_plain_machine_consumer(world):
    conn = world
    distribution.register_consumer(
        conn, name="plain-reader", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"reader").hexdigest(), created_by="seed",
        kind="machine",
    )
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    with _machine(conn) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers={"X-Consumer-Token": "reader"},
        )
    assert r.status_code == 403
    assert "不是 fleet 种类" in r.json()["detail"]


def test_a_fleet_cannot_write_back_a_round_under_another_fleets_ref(world):
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": "fleet:fleet_other/post_1#1", "role": "concept",
                  "outcome": "ok"},
            headers=_machine_headers(),
        )
    assert r.status_code == 403
    assert "runner_ref 必须形如" in r.json()["detail"]


def test_outcome_outside_the_vocabulary_is_422_not_a_row(world):
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#9", "role": "concept",
                  "outcome": "perfect"},
            headers=_machine_headers(),
        )
    assert r.status_code == 422
    assert "结局必须是" in r.json()["detail"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE origin = 'fleet'"
    ).fetchone()["n"] == 0


def test_writeback_without_a_role_is_refused(world):
    """台账第一列是岗位；允许空岗位，「谁在跑」就永久缺一角。"""
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#1", "outcome": "ok"},
            headers=_machine_headers(),
        )
    assert r.status_code == 422
    assert "role 不能为空" in r.json()["detail"]


def test_writeback_cannot_reference_a_task_outside_the_domain(world):
    conn = world
    other = workspaces.instantiate_domain(
        conn, key="other-domain", name="别域", template_name="loop-tpl",
        template_version=None, created_by="seed",
    )
    # 别域的那张单派给别域的舰队：本域舰队在那边根本不是可用登记，创建期就会被
    # 拒——所以要造出「跨域 task_id」这个局面，得让别域自有一支舰队。
    other_ref = "fleet_other_domain"
    distribution.register_consumer(
        conn, name="other-domain-fleet", domains=["other-domain"],
        token_hash=hashlib.sha256(b"other-domain-token").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref=other_ref,
    )
    from src.bench import authoring

    foreign = authoring.authoring_create_task(
        conn, domain_id=other["id"], assignee="other-domain-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=other_ref,
    )
    with _machine(conn) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#1", "role": "concept",
                  "outcome": "ok", "task_id": foreign["id"]},
            headers=_machine_headers(),
        )
    assert r.status_code == 404, r.text


def test_a_malformed_completion_body_is_422_not_a_silent_note(world):
    """空体可以关单；**写坏的 JSON 不行**——当成空体处理，舰队会以为 note 记上了。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    with _machine(conn) as m:
        m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
               headers=_machine_headers())
        bad = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            content='{"note": "少了右括号"'.encode("utf-8"),
            headers={**_machine_headers(), "Content-Type": "application/json"},
        )
        empty = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            headers=_machine_headers(),
        )
    assert bad.status_code == 422
    assert "JSON 对象" in bad.json()["detail"]
    assert empty.status_code == 200, empty.text
    assert empty.json()["task"]["status"] == "done"
