"""Typed publication pull surface (change add-typed-publications §3).

HTTP only, through the same two client patterns as ``test_distribution_web``:

- ``_bare_client`` (only ``get_db`` overridden) — the token IS the auth;
- ``_client`` for the Logto-side publish action.

The kinds used here are the *real* pack declarations (``packs.legal.
asset_catalog`` registers ``rubric`` and ``sample`` when the console imports
it), so these tests exercise the production projection SQL, not a fixture copy.
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

A_KEY = "typed-a-key"
B_KEY = "typed-b-key"
TEMPLATE_NAME = "typed-publication-template"

# Importing the pack registers its publication kinds (``rubric`` / ``sample``)
# and its catalog providers — the app does the same on the console import.
import packs.legal.asset_catalog  # noqa: E402,F401


@pytest.fixture()
def world(seeded_db):  # noqa: F811 - provided by tests/conftest.py
    """Two domains; A's shelf carries the two seeded rubrics."""
    conn = seeded_db
    conn.execute(
        "DELETE FROM knowledge_units WHERE namespace IN (%s, %s)", (A_KEY, B_KEY)
    )
    conn.execute("DELETE FROM domain_assets")
    conn.execute("DELETE FROM asset_publications")
    conn.execute("DELETE FROM asset_pull_events")
    conn.execute("DELETE FROM ontology_publications")
    conn.commit()
    templates.create_template(
        conn,
        name=TEMPLATE_NAME,
        schema={
            "entity_types": ["company"],
            "concept_structures": {},
            "relationship_kinds": ["belongs_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {},
        },
        created_by="seed",
    )
    a = workspaces.instantiate_domain(
        conn, key=A_KEY, name="甲域", template_name=TEMPLATE_NAME,
        template_version=None, created_by="seed",
    )
    workspaces.instantiate_domain(
        conn, key=B_KEY, name="乙域", template_name=TEMPLATE_NAME,
        template_version=None, created_by="seed",
    )
    workspaces.add_member(conn, domain_id=a["id"], user_id="lara", role="lead",
                          added_by="seed")
    # The two rubrics seeded by ``seed_db``; shelving is the only ownership fact.
    from src.bench import domain_assets

    for name in ("h_rubric", "l_rubric"):
        domain_assets.assign(
            conn, domain_key=A_KEY, asset_kind="rubric", asset_key=name,
            added_by="seed",
        )
    return conn


def _publish_kind(conn, kind: str = "rubric", domain_key: str = A_KEY) -> dict:
    return distribution.publish_asset_kind(
        conn, domain_key=domain_key, asset_kind=kind, published_by="lara"
    )


def _consumer(conn, name: str, domains: str, token: str) -> None:
    distribution.register_consumer(
        conn, name=name, domains=domains.split(","),
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by="admin",
    )


def _client(db, user: User) -> TestClient:
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _bare_client(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _pull(client: TestClient, domain_key: str, kind: str, token=None, **query):
    headers = {"X-Consumer-Token": token} if token is not None else {}
    return client.get(
        f"/api/v1/distribution/{domain_key}/{kind}", params=query or None,
        headers=headers,
    )


def _footprints(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM asset_pull_events").fetchone()["n"]


# ---------------------------------------------------------------- 3.3 / 3.4


def test_successful_pull_returns_the_version_and_leaves_a_footprint(world):
    publication = _publish_kind(world)
    _consumer(world, "wire", A_KEY, "tok-wire")

    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "rubric", token="tok-wire")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == A_KEY
    assert body["kind"] == "rubric"
    assert body["publication_version"] == publication["version"]
    assert body["digest"] == publication["digest"]
    assert body["shape_version"] == 1
    assert [e["asset_key"] for e in body["entries"]] == ["h_rubric", "l_rubric"]
    assert body["changelog"] == {"initial": True, "counts": {"entries": 2}}
    assert _footprints(world) == 1


def test_cross_domain_pull_is_403_and_leaves_no_footprint(world):
    _publish_kind(world)
    _consumer(world, "peeker", B_KEY, "tok-peek")

    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "rubric", token="tok-peek")
    assert r.status_code == 403
    assert r.json()["detail"] == "该域不在绑定范围"
    assert _footprints(world) == 0


def test_revoked_consumer_is_403_and_leaves_no_footprint(world):
    _publish_kind(world)
    _consumer(world, "gone", A_KEY, "tok-gone")
    distribution.revoke_consumer(world, name="gone")

    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "rubric", token="tok-gone")
    assert r.status_code == 403
    assert r.json()["detail"] == "令牌已吊销"
    assert _footprints(world) == 0


def test_missing_token_is_401_and_leaves_no_footprint(world):
    _publish_kind(world)
    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "rubric")
    assert r.status_code == 401
    assert _footprints(world) == 0


def test_auth_precedes_kind_resolution(world):
    """An anonymous caller must not learn the deployment's kind list."""
    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "prompt")
    assert r.status_code == 401
    assert "sample" not in r.text


def test_unregistered_kind_is_400_naming_the_registered_kinds(world):
    _consumer(world, "wire", A_KEY, "tok-wire")
    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "prompt", token="tok-wire")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "rubric" in detail and "sample" in detail
    assert _footprints(world) == 0


def test_a_pinned_version_that_does_not_exist_is_404(world):
    _publish_kind(world)
    _consumer(world, "wire", A_KEY, "tok-wire")
    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "rubric", token="tok-wire", version=9)
    assert r.status_code == 404
    assert _footprints(world) == 0


# ---------------------------------------------------------------- 3.1 / 3.5


def test_existing_fixed_routes_are_not_shadowed_by_the_kind_route(world):
    """``/rulers`` must keep matching its own handler, not the kind wildcard.

    A fleet-only route answers 403 "not a fleet registration" to a machine
    consumer — the wildcard handler would have answered 400 "unregistered kind".
    """
    _consumer(world, "wire", A_KEY, "tok-wire")
    with _bare_client(world) as client:
        r = client.get(
            f"/api/v1/distribution/{A_KEY}/rulers",
            headers={"X-Consumer-Token": "tok-wire"},
        )
    assert r.status_code == 403
    assert "舰队" in r.json()["detail"]


def test_ontology_still_answers_with_unchanged_fields_and_digest(world):
    """3.5: the ontology pull is byte-stable — same fields, same digest."""
    from src.bench import authoring

    authoring.authoring_create_unit(
        world, domain_key=A_KEY, kind="company", external_key="alpha-corp",
        body="正文", operator="lara",
    )
    publication = distribution.publish_domain(
        world, domain_key=A_KEY, published_by="lara"
    )
    _consumer(world, "wire", A_KEY, "tok-wire")

    with _bare_client(world) as client:
        r = _pull(client, A_KEY, "ontology", token="tok-wire")

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "domain", "template_name", "template_version", "publication_version",
        "digest", "entities", "relationships", "changelog",
    }
    assert body["digest"] == publication["digest"]
    assert body["publication_version"] == publication["version"]
    assert [e["external_key"] for e in body["entities"]] == ["alpha-corp"]


def test_publish_button_is_per_kind_and_refuses_an_empty_kind(world):
    # Both scopes: the page GET is gated on content:read, the POST on content:write.
    lara = User(sub="lara", name="lara", email="lara@example.com",
                scopes=["content:read", "content:write"], channel="test")
    with _client(world, lara) as client:
        ok = client.post(
            f"/d/{A_KEY}/publish/rubric", data={}, follow_redirects=False
        )
        empty = client.post(
            f"/d/{A_KEY}/publish/sample", data={}, follow_redirects=False
        )
    assert ok.status_code == 303 and "msg=console.flash.published_kind" in ok.headers["location"]
    assert empty.status_code == 303 and "err=1" in empty.headers["location"]

    page = None
    with _client(world, lara) as client:
        page = client.get(f"/d/{A_KEY}/publish")
    assert page.status_code == 200
    assert "按种类的发布" in page.text
    assert "/api/v1/distribution/typed-a-key/rubric" in page.text
    assert _footprints(world) == 0