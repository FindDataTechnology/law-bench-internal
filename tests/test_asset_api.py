"""Machine asset transfer API (change add-bench-asset-portability).

Pins the capability boundary: the credential must be kind='deployment-assets',
not a generic machine token and certainly not an admin identity. Auth failures
are three-state (401 / 403 / 403), and unknown asset classes name the allowed
set instead of 404-ing.
"""

from __future__ import annotations

import hashlib

import pytest

from src.bench import distribution


def _register(conn, *, name: str, token: str, kind: str, domains=("legal",)):
    distribution.register_consumer(
        conn,
        name=name,
        domains=list(domains),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_by="test",
        kind=kind,
    )
    conn.commit()


def test_asset_machine_face_requires_the_scoped_kind(app_client, seeded_db, monkeypatch):
    monkeypatch.setenv("BENCH_ASSET_PORTABILITY", "1")
    _register(seeded_db, name="deploy-assets", token="fda_ok", kind="deployment-assets")
    _register(seeded_db, name="generic-machine", token="fda_machine", kind="machine")

    r = app_client.get(
        "/api/v1/assets/ontology/export",
        params={"name": "no-such-template"},
        headers={"X-Consumer-Token": "fda_ok"},
    )
    # Auth + kind pass; the missing template is the transfer layer's 400.
    assert r.status_code == 400
    assert "not found" in r.json()["detail"]

    r = app_client.get(
        "/api/v1/assets/ontology/export",
        params={"name": "no-such-template"},
        headers={"X-Consumer-Token": "fda_machine"},
    )
    assert r.status_code == 403
    assert "deployment-assets" in r.json()["detail"]


def test_asset_machine_face_is_three_state(app_client, seeded_db, monkeypatch):
    monkeypatch.setenv("BENCH_ASSET_PORTABILITY", "1")
    assert app_client.get("/api/v1/assets/ontology/export", params={"name": "x"}).status_code == 401
    r = app_client.get(
        "/api/v1/assets/ontology/export",
        params={"name": "x"},
        headers={"X-Consumer-Token": "fda_unknown"},
    )
    assert r.status_code == 403


def test_unknown_asset_class_names_the_allowed_set(app_client, seeded_db, monkeypatch):
    monkeypatch.setenv("BENCH_ASSET_PORTABILITY", "1")
    _register(seeded_db, name="deploy-assets", token="fda_ok", kind="deployment-assets")
    r = app_client.get(
        "/api/v1/assets/dataset/export",
        params={"name": "x"},
        headers={"X-Consumer-Token": "fda_ok"},
    )
    assert r.status_code == 400
    assert "ontology" in r.json()["detail"]


def test_domain_assets_need_a_bound_domain(app_client, seeded_db, monkeypatch):
    monkeypatch.setenv("BENCH_ASSET_PORTABILITY", "1")
    _register(seeded_db, name="deploy-assets", token="fda_ok", kind="deployment-assets", domains=("legal",))
    r = app_client.get(
        "/api/v1/assets/ruler/export",
        params={"name": "legal", "domain_key": "other-domain"},
        headers={"X-Consumer-Token": "fda_ok"},
    )
    assert r.status_code == 403
    assert "不在凭据绑定范围" in r.json()["detail"]