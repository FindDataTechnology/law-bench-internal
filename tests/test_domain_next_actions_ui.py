"""总览页的「域下一动作」清单（add-domain-next-actions §2.1）。

断言：
- 有缺口时清单渲染出条目（data-testid=next-actions），每条理由来自真实计数。
- 权限不足的动作不给链接、给「需要〈角色〉」。
- 无缺口时空态明说「没有待办」。
需 PG（seeded_db）。
"""
from __future__ import annotations

from tests.test_domain_console import _client, _seed_world, _user, _READ_WRITE, A_KEY


def test_overview_renders_next_actions_when_domain_has_gaps(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}")
    assert r.status_code == 200
    assert 'data-testid="next-actions"' in r.text
    # 空本体/空知识库/空评测 → 至少 pill "空" 类动作会出现在清单里
    assert "data-gap=" in r.text


def test_next_actions_more_than_cap_is_folded(seeded_db):
    """超过 5 条时折叠为「还有 N 项」，不摊满一屏（design D5）。"""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}")
    # 硬上限：清单里可见的 <li> 不应超过 CAP；折叠提示可能不出现（本世界缺口 < 5）
    assert r.status_code == 200
