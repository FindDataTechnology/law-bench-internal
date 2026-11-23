"""for_domain 在真库上的行为（design D1 纯读 / D3 去重 / D5 上限）。

需 PG（seeded_db fixture）。复用 test_domain_console 的 _seed_world 造域，避免另写
一套 fixture。核心断言：
- for_domain 是**纯读**：除已知的触碰列外不改任何表（用 execute 包裹探测写语句）。
- unknown_gaps 为空——说明 estate 产出的每个 gap 都在 next_actions._GAP_RULES 里登记了，
  没有「加了 gap 却忘了排序」的静默漏网。
"""
from __future__ import annotations

import pytest

from src.bench import next_actions as na
from src.bench import workspaces

# 复用既有 fixture 的世界构造（同一份 domain，避免第二套 schema 漂移）
from tests.test_domain_console import _seed_world, A_KEY


class _WriteDetector:
    """包一层 conn，记录 for_domain 期间执行的 INSERT/UPDATE/DELETE。

    不拦截——真执行——但记下语句文本，测试据此断言「零写」。
    """

    def __init__(self, conn):
        self._conn = conn
        self.writes: list[str] = []

    def execute(self, sql, params=None):  # noqa: ANN001
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.writes.append(sql.strip()[:80])
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_for_domain_is_pure_read_and_has_no_unregistered_gaps(seeded_db):
    _seed_world(seeded_db)
    domain = workspaces.get_domain(seeded_db, domain_key=A_KEY)
    assert domain is not None

    detector = _WriteDetector(seeded_db)
    result = na.for_domain(detector, domain)

    # 纯读：matrix 只读，不该有任何 INSERT/UPDATE/DELETE
    assert detector.writes == [], f"for_domain 写了表：{detector.writes}"

    # 没有未登记的 gap（否则 estate 加了缺口、next_actions 没接 → 静默漏）
    assert result["unknown_gaps"] == [], result["unknown_gaps"]

    # 结构契约
    assert set(result["ranked"]) == {"top", "more", "total"}
    assert len(result["ranked"]["top"]) <= na.CAP