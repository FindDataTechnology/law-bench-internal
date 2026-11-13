"""迁移脚本 register_fleet.py 的守门行为（add-fleet-execution-loop §2.5）。

脚本是这次切换里唯一「机器读历史、人做决定」的交界，所以它必须守住三件事：

- **不自动登记**：``--from-observed`` 只打印。把「见过的一串字」变成「身份」正是
  这个 change 要拆掉的东西，脚本不能自己做这个替换。
- **不发明凭据**：``--apply`` 没拿到**现有** token 就拒绝。现场登记凭证会把正在
  跑的舰队当场切断，而且一个编出来的 hash 谁也进不来。
- **迁移计数把 NULL 单列**：列还不存在时写入的行没有任何判定可读，它们是货真价实
  的遗留，但不能伪装成某个 verdict——否则人会以为「只是少改了一个字段」。
"""

from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path

import pytest

from src.bench import distribution, proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "register_fleet.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("register_fleet_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db


def _borrowed(conn):
    """main() 的 finally 会 close 连接；测试里这条连接归 fixture，包一层不让它被关。"""
    from src.eval.db import _BorrowedConn

    return _BorrowedConn(conn)


def _submit(conn, source, key):
    proposals.submit(
        conn, domain_key="legal", source=source, kind="company", external_key=key,
        body="b", evidence={"quote": "q-" + key}, submitted_by=source,
        via="in_process",
    )


# --------------------------------------------------------------- --legacy


def test_legacy_says_none_when_everything_passes(conn, capsys, monkeypatch):
    monkeypatch.delenv("BENCH_SUBMITTER_MODE", raising=False)
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    assert script.main(["--legacy"]) == 0
    assert "legacy sources: none" in capsys.readouterr().out


def test_a_row_written_before_the_column_is_reported_as_unknown(conn, capsys):
    """NULL verdict 不能装成某个具体结论，也不能被漏掉。"""
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'extract:qwen:2025-10', 'company', 'lg-1', 'b', '{}'::jsonb, 'd1', "
        "'pending', 'extract:qwen:2025-10', '[\"extract:qwen:2025-10\"]'::jsonb FROM domains"
    )
    conn.commit()

    script = _load_script()
    monkeyio = pytest.MonkeyPatch()
    monkeyio.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--legacy"]) == 0
    finally:
        monkeyio.undo()

    out = capsys.readouterr().out
    assert "extract:qwen:2025-10" in out
    assert "(历史行·无判定)" in out
    assert "1 行没有任何判定" in out


# ------------------------------------------------------- --from-observed


def test_observed_lists_unregistered_and_registered_side_by_side(conn, capsys):
    distribution.register_consumer(
        conn, name="known-fleet", domains=["legal"],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_known",
    )
    _submit(conn, "fleet:fleet_known/p1", "k1")
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'fleet:credential-probe/post_probe', 'company', 'probe-1', 'b', "
        "'{}'::jsonb, 'd2', 'pending', 'probe', '[\"fleet:credential-probe/post_probe\"]'::jsonb "
        "FROM domains"
    )
    conn.commit()

    script = _load_script()
    mp = pytest.MonkeyPatch()
    mp.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--from-observed"]) == 0
    finally:
        mp.undo()

    out = capsys.readouterr().out
    assert "fleet_known" in out and "已登记" in out
    assert "credential-probe" in out and "未登记" in out
    # 这句是脚本的要害：它明说这份清单不能直接 apply。
    assert "不是一份可以直接 apply 的清单" in out
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 1


# ------------------------------------------------------------- --apply


def test_apply_without_the_existing_token_refuses(conn, capsys, monkeypatch):
    monkeypatch.delenv("BENCH_FLEET_TOKEN", raising=False)
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_new", "--domains", "legal", "--apply"]) == 1
    err = capsys.readouterr().err
    assert "will not invent one" in err
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 0


def test_apply_refuses_a_ref_that_is_already_live(conn, capsys, monkeypatch):
    distribution.register_consumer(
        conn, name="already", domains=["legal"],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_dup",
    )
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_dup", "--domains", "legal", "--apply"]) == 1
    assert "already registered" in capsys.readouterr().err


def test_dry_run_writes_nothing(conn, capsys, monkeypatch):
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_new", "--domains", "legal"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 0


def test_apply_registers_a_fleet_bound_to_its_domain(conn, monkeypatch):
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main([
        "--fleet-ref", "fleet_new", "--name", "new-fleet", "--domains", "legal", "--apply",
    ]) == 0

    row = distribution.list_consumers(conn)[0]
    assert (row["kind"], row["fleet_ref"], row["domains"]) == ("fleet", "fleet_new", ["legal"])

    # 登记之后这条来源立刻可以提交了——严格档不报错本身就是判据，
    # 落库的 verdict 再确认一次。
    proposals.submit(
        conn, domain_key="legal", source="fleet:fleet_new/post_1", kind="company",
        external_key="k9", body="b", evidence={"quote": "q"},
        submitted_by="fleet:fleet_new/post_1", via="in_process",
    )
    verdict = conn.execute(
        "SELECT submitter_verdict FROM domain_proposals WHERE external_key = 'k9'"
    ).fetchone()["submitter_verdict"]
    assert verdict == "ok"
