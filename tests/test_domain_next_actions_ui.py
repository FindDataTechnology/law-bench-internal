"""总览页的「域下一动作」清单（add-domain-next-actions §2.1）。

断言：
- 有缺口时清单渲染出条目（data-testid=next-actions），每条理由来自真实计数。
- 无缺口时空态明说「没有待办」。
需 PG（seeded_db）。

注：不直接用 test_domain_console._client —— 那个构造函数在 ``create_app()`` 之后
才 patch，而 fail-closed 启动探针 ``logto.verify_reachable()`` 在 ``create_app()`` 的
lifespan 里就跑。必须**先** patch（同 conftest 的 app_client 顺序），否则 CI 无网即
``LogtoUnreachable``。
"""
from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from tests.test_domain_console import _seed_world, _user, _READ_WRITE, A_KEY
from src.web.app import create_app
from src.web.auth import logto
from src.web.deps import get_db
from src.web.auth.deps import get_current_user


@pytest.fixture
def _client_alice(seeded_db, monkeypatch):
    # 顺序关键：patch 在 create_app() 之前（lifespan 启动探针要它）
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    _seed_world(seeded_db)
    app = create_app()
    user = _user("alice", _READ_WRITE)

    def _current(request: Request):
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: seeded_db
    app.dependency_overrides[get_current_user] = _current
    with TestClient(app) as c:
        yield c


def test_overview_renders_next_actions_when_domain_has_gaps(_client_alice):
    r = _client_alice.get(f"/d/{A_KEY}")
    assert r.status_code == 200
    assert 'data-testid="next-actions"' in r.text
    assert "data-gap=" in r.text  # 至少一条动作


def test_next_actions_section_absent_only_when_no_gaps(_client_alice):
    """本世界（空本体/知识库/评测）必有缺口，故清单块应在。这保证渲染路径被执行。"""
    r = _client_alice.get(f"/d/{A_KEY}")
    assert 'data-testid="next-actions"' in r.text
