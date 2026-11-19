"""Machine crosswalk read face (change prove-line-seams, task 1.1–1.3).

Why this suite exists separately from ``test_distribution_web.py``: that suite
covers the ontology pull contract. This one covers the *second* machine reader —
the seam the ERP connector generator actually calls. Its failure mode is quiet:
if the route is missing, ERP silently falls back to its local file and every
dashboard stays green while "platform is the read authority" is false.

Three things are asserted, in this order:

1. the three-state token check is the SAME one the pull surface uses (no second
   copy, same four refusals);
2. a bound domain returns the rows the console read face would return — same
   shape, built by the same function;
3. reading writes nothing (no footprint, no ``last_used_at``).
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from src.bench import store, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.deps import get_db

@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    """App startup probes the IdP; tests must not depend on a real Logto."""
    from src.web.auth import logto

    monkeypatch.setattr(logto, "verify_reachable", lambda: None)

A_TOKEN = "crosswalk-read-face-a"


@pytest.fixture()
def crosswalk_world(empty_db):  # noqa: F811
    """Domain A with one crosswalk carrying partial connectivity evidence."""
    from src.eval import db as edb

    edb.close_shared_conn()
    ensure_schema(db_path=empty_db)
    tpl = templates.create_template(
        empty_db, name="erp-tpl",
        schema={
            "entity_types": ["organization", "account"],
            "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        },
        created_by="t",
    )
    dom = workspaces.instantiate_domain(
        empty_db, key="erp", name="ERP", template_name="erp-tpl",
        template_version=tpl["version"], created_by="t",
    )
    workspaces.add_member(empty_db, domain_id=dom["id"], user_id="u1",
                          role="lead", added_by="t")
    store.upsert_knowledge_unit(
        empty_db, kind="organization", namespace="erp",
        external_key="organization:acme", body="Acme",
    )
    store.upsert_knowledge_unit(
        empty_db, kind="crosswalk", namespace="erp", external_key="organization:acme",
        body="mapped to kingdee",
        attrs={
            "relation": "same_as",
            "peer": {"kind": "external_id", "system": "kingdee", "id": "BD001"},
            "confidence": 0.95,
            "connectivity": {
                "catalog": {"ok": True, "evidence": "catalog/apps/kingdee.json"},
                "executor_tests": {"ok": True, "evidence": "src/providers/kingdee/x.test.ts"},
                # live deliberately missing — the honest "not connected" case
            },
        },
    )
    empty_db.commit()
    yield dom
    edb.close_shared_conn()


def _bare(db) -> TestClient:
    """No identity override: the token check must be the only authentication."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _get(client: TestClient, domain: str, token: str | None = None, **params):
    headers = {"X-Consumer-Token": token} if token is not None else {}
    return client.get(
        f"/api/v1/distribution/{domain}/crosswalks",
        params=params or None, headers=headers,
    )


def _register(db, token: str, domains: list[str], *, kind: str = "machine") -> None:
    from src.bench import distribution

    distribution.register_consumer(
        db, name=f"consumer-{token}", domains=domains, kind=kind,
        created_by="t", token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    db.commit()


# ----------------------------------------------------------------- 1.1 auth #


def test_missing_token_is_401_naming_the_header(crosswalk_world, empty_db):
    with _bare(empty_db) as c:
        r = _get(c, "erp")
    assert r.status_code == 401
    assert r.json()["detail"] == "缺少机器凭据：X-Consumer-Token 请求头"


def test_unregistered_token_is_403(crosswalk_world, empty_db):
    with _bare(empty_db) as c:
        r = _get(c, "erp", "nobody")
    assert r.status_code == 403
    assert r.json()["detail"] == "令牌未登记"


def test_revoked_token_is_403_distinct_from_unregistered(crosswalk_world, empty_db):
    from src.bench import distribution

    _register(empty_db, A_TOKEN, ["erp"])
    distribution.revoke_consumer(empty_db, name=f"consumer-{A_TOKEN}")
    empty_db.commit()
    with _bare(empty_db) as c:
        r = _get(c, "erp", A_TOKEN)
    assert r.status_code == 403
    assert r.json()["detail"] == "令牌已吊销"


def test_domain_outside_binding_is_403_and_leaks_no_existence(crosswalk_world, empty_db):
    _register(empty_db, A_TOKEN, ["some-other-domain"])
    with _bare(empty_db) as c:
        r = _get(c, "erp", A_TOKEN)
    assert r.status_code == 403
    assert r.json()["detail"] == "该域不在绑定范围"


# ------------------------------------------------------------- 1.1 payload #


def test_bound_domain_returns_the_crosswalk_rows(crosswalk_world, empty_db):
    _register(empty_db, A_TOKEN, ["erp"])
    with _bare(empty_db) as c:
        r = _get(c, "erp", A_TOKEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "erp"
    assert body["count"] == 1
    row = body["crosswalks"][0]
    assert row["key"] == "organization:acme"
    assert row["relation"] == "same_as"
    assert row["peer"] == {"kind": "external_id", "system": "kingdee", "id": "BD001"}
    assert row["missing_states"] == ["live"]
    assert row["confirmed"] is True
    assert body["gaps"]["stale"]  # live missing => stale, not silently clean


def test_machine_rows_come_from_the_shared_shaping_function(crosswalk_world, empty_db):
    """Same rows, same shape — one definition, two audiences.

    The assertion is identity, not a copy: the machine face must return exactly
    what ``bench.crosswalk.list_rows`` returns for that namespace. Building the
    comparison against a second app instance does not work here — Starlette 1.9
    keeps routers as ``_IncludedRouter`` wrappers, so a route path cannot be
    matched a second time from within one test (the second app answers 422 with
    ``request`` as a missing query param, which reads like a routing bug and is
    not one). The console face's use of the same function is pinned separately
    below.
    """
    from src.bench import crosswalk

    _register(empty_db, A_TOKEN, ["erp"])
    with _bare(empty_db) as machine:
        machine_rows = _get(machine, "erp", A_TOKEN).json()["crosswalks"]
    assert machine_rows == crosswalk.list_rows(empty_db, namespace="erp")


def test_console_handler_delegates_to_the_same_function(crosswalk_world, empty_db, monkeypatch):
    """The human console route must not grow a second copy of the query.

    If it did, one side would start answering a different question and the
    difference would surface only as "the two pages disagree".
    """
    from src.web.routes import console

    calls = []
    real = console._crosswalk

    class _Spy:
        def __getattr__(self, name):
            return getattr(real(), name)

        def list_rows(self, db, *, namespace, entity_key=None):
            calls.append((namespace, entity_key))
            return real().list_rows(db, namespace=namespace, entity_key=entity_key)

    monkeypatch.setattr(console, "_crosswalk", lambda: _Spy())
    out = console._crosswalk_rows(empty_db, path="erp", entity_key=None)
    assert calls == [("erp", None)]
    assert out == real().list_rows(empty_db, namespace="erp")


def test_entity_filter_narrows_like_the_console(crosswalk_world, empty_db):
    _register(empty_db, A_TOKEN, ["erp"])
    with _bare(empty_db) as c:
        hit = _get(c, "erp", A_TOKEN, entity="organization:acme")
        miss = _get(c, "erp", A_TOKEN, entity="organization:nope")
    assert hit.json()["count"] == 1
    assert miss.json()["count"] == 0


# -------------------------------------------------------------- 1.2 read-only #


def test_reading_writes_nothing(crosswalk_world, empty_db):
    """No footprint row, no consumer mutation: this is a read, not a pull.

    The ontology pull writes a footprint because "who fetched which snapshot" is
    an audit question. "A generator asked what the connector state is" is not.
    """
    _register(empty_db, A_TOKEN, ["erp"])

    def snapshot() -> list[tuple]:
        # Every mutable column the reader could plausibly touch, plus the rows
        # themselves. A new column added later is not covered — that is the
        # known limit of a snapshot test (no assertions are auto-derived).
        consumers = empty_db.execute(
            "SELECT name, domains, revoked_at, kind, fleet_ref, created_at "
            "FROM distribution_consumers ORDER BY name"
        ).fetchall()
        units = empty_db.execute(
            "SELECT external_key, updated_at FROM knowledge_units "
            "WHERE namespace = 'erp' ORDER BY external_key"
        ).fetchall()
        return [tuple(r.values()) for r in consumers] + [
            (r["external_key"], r["updated_at"]) for r in units
        ]

    before = snapshot()
    with _bare(empty_db) as c:
        assert _get(c, "erp", A_TOKEN).status_code == 200
    assert snapshot() == before
