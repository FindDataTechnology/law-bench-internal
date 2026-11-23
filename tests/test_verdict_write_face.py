"""Verdict write face + domain admission (openspec bind-verdict-write-to-domain-admission).

The write face is a NEW trust boundary, so the negative cases matter more than
the happy path: an unregistered ruler, a mismatched identity claim, and a subject
outside the domain all have to be refused with DIFFERENT reasons (their remedies
point at different layers). These tests pin each gate and the "no write to the
wrong layer" property.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from src.bench import domain_rubrics, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.bench import verdicts as bench_verdicts
from src.eval import store as eval_store
from src.web.app import create_app
from src.web.deps import get_db


A_KEY = "vw-a"

_SCHEMA = {
    "entity_types": ["clause"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites_law"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(seeded_db):  # noqa: F811 - tests/conftest.py
    # Use seeded_db, NOT empty_db: empty_db creates and DROPs a per-test database,
    # but create_app()'s connection stays attached to it and the DROP hits
    # ObjectInUse (documented in tests/test_run_readback.py). The session DB has
    # the real schema (rubrics/criteria/eval_runs) and is TRUNCATEd per test.
    eval_store._ensured_dbs.clear()
    eval_store.ensure_schema(db_path=seeded_db)
    yield seeded_db


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    from src.web.auth import logto
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _client(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _register(conn, name: str, domains: str) -> str:
    """Register a fleet consumer; return its plaintext token."""
    from src.bench import distribution

    import secrets
    token = secrets.token_urlsafe(32)
    distribution.register_consumer(
        conn, name=name, domains=[domains] if isinstance(domains, str) else domains,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_by="seed", kind="fleet", fleet_ref=name,
    )
    conn.commit()
    return token


def _world(conn):
    templates.create_template(conn, name="tpl", schema=dict(_SCHEMA), created_by="seed")
    d = workspaces.instantiate_domain(
        conn, key=A_KEY, name="域A", template_name="tpl",
        template_version=None, created_by="seed",
    )
    rubric = domain_rubrics.create_for_domain(
        conn, domain_id=d["id"], name="quality", context="check",
        criteria=[{"name": "c1", "description": "d", "guidance": "g"}],
    )
    ruler = bench_verdicts.rubric_ruler("quality", db_path=conn)
    return d, rubric, ruler


def _payload(ruler: dict, **over) -> dict:
    body = {
        "subject_kind": "clause", "subject_key": "clause-1", "subject_version": "1",
        "ruler_kind": ruler["kind"], "ruler_key": ruler["key"],
        "ruler_digest": ruler["digest"], "ruling_domain_path": A_KEY,
        "gate": "all-pass", "outcome": "pass",
    }
    body.update(over)
    return body


def _post(client, token, body, domain=A_KEY):
    return client.post(
        f"/api/v1/distribution/{domain}/verdicts",
        json=body, headers={"X-Consumer-Token": token},
    )


def test_a_well_formed_verdict_lands_and_is_readable(conn):
    d, rubric, ruler = _world(conn)
    token = _register(conn, "fleet_a", A_KEY)
    client = _client(conn)

    r = _post(client, token, _payload(ruler))
    assert r.status_code == 200, r.text
    assert r.json()["verdict_state"] == "landed"
    run_id = r.json()["verdict"]["run_id"]

    row = eval_store.get_run(run_id, db_path=conn)
    assert row["outcome"] == "pass"
    assert row["ruler_digest"] == ruler["digest"]
    # Layer is resolved from the ruler's owning domain, not the body.
    assert row["ruling_domain_path"] == A_KEY


def test_an_unregistered_ruler_is_refused_naming_the_ruler_gate(conn):
    _world(conn)
    token = _register(conn, "fleet_a", A_KEY)
    client = _client(conn)
    body = {
        "subject_kind": "clause", "subject_key": "clause-1", "subject_version": "1",
        "ruler_kind": "rubric", "ruler_key": "made-up",
        "ruler_digest": "f" * 64, "ruling_domain_path": A_KEY,
        "gate": "all-pass", "outcome": "pass",
    }
    r = _post(client, token, body)
    assert r.status_code == 422
    assert "尺子门" in r.json()["detail"]


def test_identity_claim_cannot_speak_for_another_fleet(conn):
    _d, _r, ruler = _world(conn)
    token = _register(conn, "fleet_a", A_KEY)
    client = _client(conn)
    r = _post(client, token, _payload(ruler, source="fleet:someone_else/post"))
    assert r.status_code == 403
    assert "身份门" in r.json()["detail"]


def test_missing_layer_field_is_refused(conn):
    _d, _r, ruler = _world(conn)
    token = _register(conn, "fleet_a", A_KEY)
    client = _client(conn)
    body = _payload(ruler)
    body.pop("ruling_domain_path")
    r = _post(client, token, body)
    assert r.status_code == 422
    assert "ruling_domain_path" in r.json()["detail"]


def test_a_machine_kind_is_refused_as_a_kind_not_a_credential_problem(conn):
    from src.bench import distribution
    import secrets

    _d, _r, ruler = _world(conn)
    token = secrets.token_urlsafe(32)
    distribution.register_consumer(
        conn, name="reader", domains=[A_KEY],
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_by="seed", kind="machine",
    )
    conn.commit()
    client = _client(conn)
    r = _post(client, token, _payload(ruler))
    assert r.status_code == 403
    assert "fleet 种类" in r.json()["detail"]


def test_verdicts_are_append_only_no_update_path(conn):
    """Two verdicts for the same subject are two rows, never a rewrite."""
    d, rubric, ruler = _world(conn)
    token = _register(conn, "fleet_a", A_KEY)
    client = _client(conn)

    first = _post(client, token, _payload(ruler, outcome="pass")).json()["verdict"]["run_id"]
    second = _post(client, token, _payload(ruler, outcome="fail")).json()["verdict"]["run_id"]
    assert first != second
    # The first row is untouched.
    assert eval_store.get_run(first, db_path=conn)["outcome"] == "pass"
    assert eval_store.get_run(second, db_path=conn)["outcome"] == "fail"


# --- admission abstraction -------------------------------------------------- #


def test_list_principals_returns_people_agents_and_fleets_together(conn):
    d, _, _ = _world(conn)
    workspaces.add_member(conn, domain_id=d["id"], user_id="alice", role="expert", added_by="seed")
    workspaces.add_member(conn, domain_id=d["id"], user_id="agent:concept@a", role="expert", added_by="seed")

    rows = workspaces.list_principals(
        conn, domain_id=d["id"],
        a2a_consumers=[{"fleet_ref": "fleet_a"}],
    )
    by_ref = {r["ref"]: r for r in rows}
    assert by_ref["alice"]["kind"] == "user"
    assert by_ref["agent:concept@a"]["kind"] == "agent"
    assert by_ref["fleet_a"]["kind"] == "fleet"
    assert by_ref["fleet_a"]["role"] is None  # a fleet holds no role, not a default


def test_admit_principal_cannot_grant_a_machine_lead(conn):
    d, _, _ = _world(conn)
    with pytest.raises(PermissionError):
        workspaces.admit_principal(
            conn, domain_id=d["id"], kind="agent",
            ref="agent:x@a", role="lead", added_by="seed",
        )


def test_admit_principal_refuses_unknown_kind_and_fleet_insert(conn):
    d, _, _ = _world(conn)
    with pytest.raises(ValueError):
        workspaces.admit_principal(conn, domain_id=d["id"], kind="team", ref="x", role="expert", added_by="seed")
    with pytest.raises(ValueError):
        workspaces.admit_principal(conn, domain_id=d["id"], kind="fleet", ref="fleet_a", role=None, added_by="seed")
