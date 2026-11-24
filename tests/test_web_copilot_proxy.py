"""Tests for the ``/copilotkit`` domain-assistant proxy.

Change ``scope-assistant-to-domain`` replaced the platform ``admin`` scope gate
with a **domain membership** gate: the caller must be an active member of the
domain the island says it is in. These tests exercise the real gate (no
dependency override on the admission path), so 401 (unauthenticated) vs 403
(no membership) vs 200 (member, proxied+streamed) and the 503 (runtime
unconfigured) fail-closed behaviour are actually under test.

They also pin the two things that made the old gate wrong: an admin with no
membership in the requested domain is refused like anyone else (the change
removed the admin shortcut on purpose), and a client cannot smuggle its own
role by sending the header — the proxy overwrites it from the database.
"""

from __future__ import annotations

import typing

import httpx
import pytest
from fastapi.testclient import TestClient

from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import logto, session
from src.web.auth.scopes import scopes_from_claims
from src.bench import templates as bench_templates
from src.bench import workspaces
from src.web.deps import get_db
from src.web.routes import copilot as copilot_routes

DOMAIN_KEY = "copilot-domain"
_READ_WRITE = ["content:read", "content:write"]


def _seed_domain(conn, *, member_subs: dict[str, str]) -> None:
    """One domain with the given ``{sub: role}`` memberships.

    Re-running is safe: membership is append-only, so an existing active row for
    the same user would make ``add_member`` a no-op at best and a conflict at
    worst — this file only ever adds users it does not already have.
    """
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    schema = {
        "entity_types": ["clause"],
        "concept_structures": {"clause": ["id"]},
        "relationship_kinds": ["cites_law"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
    }
    existing = workspaces.get_domain(conn, domain_key=DOMAIN_KEY)
    if existing is None:
        bench_templates.create_template(
            conn, name="copilot-tpl", schema=schema, created_by="seed"
        )
        domain = workspaces.instantiate_domain(
            conn, key=DOMAIN_KEY, name="副驾驶域", template_name="copilot-tpl",
            template_version=None, created_by="seed",
        )
    else:
        domain = existing
    have = {
        m["user_id"]
        for m in workspaces.list_members(conn, domain_id=domain["id"])
        if m.get("active", True) is not False
    }
    for sub, role in member_subs.items():
        if sub not in have:
            workspaces.add_member(
                conn, domain_id=domain["id"], user_id=sub, role=role, added_by="seed"
            )
    conn.commit()


@pytest.fixture
def proxy_client(seeded_db, monkeypatch) -> TestClient:
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


def _cookie(payload: dict) -> str:
    return session._serializer().dumps(session._normalize(payload))


def _login(client: TestClient, sub: str, scopes: list[str]) -> None:
    normalized = scopes_from_claims({"scope": " ".join(scopes)})
    client.cookies.set(AUTH_COOKIE_NAME, _cookie({"sub": sub, "scopes": normalized}))


# --- mock upstream --------------------------------------------------------- #

_RECORDS: dict = {}


async def _upstream_body() -> "typing.AsyncIterator[bytes]":
    # An async generator keeps the mock response unread until iterated, the
    # same semantics as a real socket — MockTransport's `content=bytes` form
    # is eagerly read and `aiter_raw` would see it as already consumed.
    yield b'{"data":'
    yield b'{"hello":"world"}}'


def _upstream(request: httpx.Request) -> httpx.Response:
    _RECORDS["method"] = request.method
    _RECORDS["url"] = str(request.url)
    _RECORDS["headers"] = dict(request.headers)
    _RECORDS["body"] = request.read().decode()
    return httpx.Response(
        200,
        content=_upstream_body(),
        headers={"content-type": "application/json"},
    )


@pytest.fixture
def runtime_configured(monkeypatch):
    """Point the proxy at a mock upstream and record what it forwards."""
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "http://runtime.test:3111")
    monkeypatch.setattr(
        copilot_routes,
        "_build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_upstream),
            timeout=copilot_routes._TIMEOUT,
        ),
    )
    _RECORDS.clear()


# --- gating ---------------------------------------------------------------- #


def _post(client: TestClient, *, domain: str | None = DOMAIN_KEY, headers=None):
    h = {"content-type": "application/json"}
    if domain is not None:
        h["X-Lawbench-Domain"] = domain
    h.update(headers or {})
    return client.post("/copilotkit", json={"query": "{ hello }"}, headers=h)


def test_unauthenticated_is_rejected_before_proxying(proxy_client, runtime_configured):
    resp = _post(proxy_client)
    assert resp.status_code == 401
    assert not _RECORDS, "the runtime must not be reached without credentials"


def test_signed_in_without_membership_gets_403(proxy_client, runtime_configured):
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "outsider-1", _READ_WRITE)
    resp = _post(proxy_client)
    assert resp.status_code == 403
    assert resp.json()["error"] == "no_domain_context"
    assert not _RECORDS, "a non-member must not reach the runtime"


def test_admin_without_membership_is_refused_like_anyone(proxy_client, runtime_configured):
    """平台 admin 不再有捷径。

    旧门是 `require_scope("admin")`，于是没有域成员身份的管理员可以打到运行时。
    这也是这次收编要拆掉的东西之一：助手按「你在哪个域」服务，而不是按「你是不是
    平台管理员」。
    """
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "admin-1", ["admin"])
    resp = _post(proxy_client)
    assert resp.status_code == 403
    assert not _RECORDS


def test_request_without_a_domain_header_is_denied(proxy_client, runtime_configured):
    """没有域声明 = 拒绝，不退化成「无域助手」（design D4）。"""
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client, domain=None)
    assert resp.status_code == 403
    assert not _RECORDS


def test_unknown_domain_is_denied(proxy_client, runtime_configured):
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client, domain="no-such-domain")
    assert resp.status_code == 403
    assert not _RECORDS


def test_runtime_unconfigured_is_503_even_for_a_member(proxy_client, monkeypatch):
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "")
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client)
    assert resp.status_code == 503
    assert "COPILOT_RUNTIME_URL" in resp.json()["error"]


# --- member passthrough ----------------------------------------------------- #


def test_member_request_is_proxied_and_streamed(proxy_client, runtime_configured):
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client)
    assert resp.status_code == 200
    assert resp.json() == {"data": {"hello": "world"}}
    assert _RECORDS["method"] == "POST"
    assert _RECORDS["url"] == "http://runtime.test:3111/copilotkit"
    assert '"query"' in _RECORDS["body"]


def test_proxy_stamps_the_verified_domain_and_role(proxy_client, runtime_configured):
    """角色由代理从库里取，客户端发什么都被覆盖。

    这是整个角色收敛的前提：运行时侧按 `X-Lawbench-Role` 过滤工具面。如果这个头
    可以是客户端说了算，整个角色隔离就是纸糊的。
    """
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "annotator"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client, headers={"X-Lawbench-Role": "lead"})
    assert resp.status_code == 200
    assert _RECORDS["headers"]["x-lawbench-role"] == "annotator", (
        f"客户端伪造的角色被透传了：{_RECORDS['headers']['x-lawbench-role']}"
    )
    assert _RECORDS["headers"]["x-lawbench-domain"] == DOMAIN_KEY


def test_client_cannot_claim_a_domain_it_does_not_belong_to(proxy_client, runtime_configured):
    """伪造域同样无效：域按名字查、按成员资格判，客户端说了不算。

    这与角色伪造是同一类：请求头是声明，不是事实。顺带钉住「未知域被拒」和
    「已知域但非成员被拒」走的是同一条拒绝路径（都是 403 no_domain_context）。
    """
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client, domain="somewhere-else")
    assert resp.status_code == 403
    assert not _RECORDS


def test_subpath_is_forwarded(proxy_client, runtime_configured):
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = proxy_client.get(
        "/copilotkit/some/asset", headers={"X-Lawbench-Domain": DOMAIN_KEY}
    )
    assert resp.status_code == 200
    assert _RECORDS["url"] == "http://runtime.test:3111/copilotkit/some/asset"


def test_workbench_credentials_are_stripped(proxy_client, runtime_configured):
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    _post(proxy_client)
    forwarded = {k.lower() for k in _RECORDS["headers"]}
    # The workbench's own credentials must not leak to the runtime; host /
    # content-length are re-set by httpx from the upstream URL and body.
    assert "cookie" not in forwarded
    assert "authorization" not in forwarded
    assert "x-api-key" not in forwarded
    assert _RECORDS["headers"].get("content-type") == "application/json"


def test_upstream_outage_is_502(proxy_client, monkeypatch):
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "http://runtime.test:3111")

    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        copilot_routes,
        "_build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_boom), timeout=copilot_routes._TIMEOUT
        ),
    )
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    resp = _post(proxy_client)
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["error"]


# --- island rendering (base.html include) ----------------------------------- #


def _get_page(client: TestClient, path: str = "/rubrics") -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.text


def test_member_sees_the_island_on_a_domain_page(proxy_client, monkeypatch):
    # templating.py binds the setting by value at import time, so patch its
    # module attribute rather than copilot_routes'.
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    html = _get_page(proxy_client, f"/d/{DOMAIN_KEY}")
    assert 'id="lawbench-assistant-root"' in html
    assert "assistant/assistant.js" in html
    assert "assistant/style.css" in html


def test_island_carries_the_domain_key(proxy_client, monkeypatch):
    """浮岛必须把域带出去——否则它的每条请求都会被代理拒掉。"""
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    html = _get_page(proxy_client, f"/d/{DOMAIN_KEY}")
    assert f'data-domain="{DOMAIN_KEY}"' in html


def test_non_member_page_has_no_island_markup(proxy_client, monkeypatch):
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "outsider-1", _READ_WRITE)
    resp = proxy_client.get(f"/d/{DOMAIN_KEY}")
    # A non-member cannot even load the domain page (the domain gate 403s), so
    # the island question is decided upstream — assert no island in whatever
    # body came back, which is the honest statement either way.
    assert "lawbench-assistant-root" not in resp.text


def test_page_outside_a_domain_has_no_island(proxy_client, monkeypatch):
    """非域页（如 /rubrics）不该出现副驾驶——它没有域可绑（design D4）。"""
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _seed_domain(proxy_client.app.dependency_overrides[get_db](), member_subs={"member-1": "expert"})
    _login(proxy_client, "member-1", _READ_WRITE)
    assert "lawbench-assistant-root" not in _get_page(proxy_client)
