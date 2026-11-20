"""给金融域建一把「金融事实质量」尺子（幂等）。

    uv run python scripts/seed_finance_rubric.py --dry-run
    uv run python scripts/seed_finance_rubric.py

判据逐条取自 `packs/finance-data/checks.py` 的七个**已在跑**的确定性 checker
（每个都在 `register_checker(KIND, ...)` 注册、在真实金标上跑过），加一条它们
共同的前提——单元确实是金标而不是机器草稿。不新写标准：

- 值域与方向对账（`fd-data-quality` 的显式允许集 + `dashboards` finalize 的
  声明值互相对账判据）
- 原文锚点（指纹格式、长度为正）——没有锚点的「事实」不可回源
- 身份与日期（`doc_id` 与 upsert 键一致、`as_of` 可解析）
- 金额契约（有则必须可解析，无则通过）——钉住未来补金额锚点时的边界
- 档位（只认 gold）

前七条是机器可跑的；第八条是它们成立的前提，读面可核对但不能由 checker 自证。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUBRIC_NAME = "finance-fact-quality"

#: (名称, 说明, 判定指引)。前七条对应 checks.py 的七个 checker，逐条同名同义。
CRITERIA: list[tuple[str, str, str]] = [
    ("档位值域", "expected_band 必须落在五档词表内",
     "checker `band-vocabulary`：expected_band ∈ {strong_bullish, bullish, neutral, "
     "bearish, strong_bearish}。词表以 fd-sentiment 的 fd_sentiment.models.BANDS 为准。"),
    ("档位与方向一致", "direction 必须与档位推出的方向一致",
     "checker `band-direction-consistency`：两个声明字段互相矛盾即不通过——"
     "声明与数据打架的单元不许过闸。"),
    ("原文指纹格式", "text_sha256 必须是 64 位小写十六进制",
     "checker `text-fingerprint-sha256`：原文指纹是回源的锚点，格式不合法即无法定位原文。"),
    ("文本长度为正", "text_chars 必须是正整数",
     "checker `text-chars-positive`：长度为 0 或负数说明抓到了空壳，不是文本。"),
    ("身份对账", "attrs.doc_id 必须等于 upsert 键 external_key",
     "checker `doc-id-identity`：身份不一致时同一文档会有两个身份，去重与回源同时失效。"),
    ("日期可解析", "as_of 必须是可解析的 ISO 日期",
     "checker `as-of-iso-date`：日期不可解析即无法判断这条事实是哪一天的。"),
    ("金额可解析", "如存在金额字段必须可解析为数值",
     "checker `amount-anchor-parseable`：gold-v9 无金额字段，当前全部通过；"
     "本判据钉住未来补金额时的契约，坏类型的值显式 FAIL 而不是静默混入。"),
    ("单元是金标而非机器草稿", "进入本域的事实单元必须是 gold 档",
     "tier 必须是 gold。bronze/silver 永不作真值或 reward——这条是前七条成立的前提，"
     "读面可核对，但不由 checker 自证（checker 只拿到单元本身）。"),
]


def seed(conn: Any, *, domain_key: str) -> dict:
    """写入（或更新）该域的金融事实质量尺；返回 {rubric_id, criteria, visible}。"""
    from src.bench import domain_rubrics, workspaces
    from src.eval.db import now_iso

    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"域 {domain_key!r} 不存在")
    existing = conn.execute(
        "SELECT id FROM rubrics WHERE domain_id = %s AND name = %s",
        (domain["id"], RUBRIC_NAME),
    ).fetchone()
    if existing:
        rubric_id = existing["id"]
        conn.execute("DELETE FROM criteria WHERE rubric_id = %s", (rubric_id,))
    else:
        rubric_id = conn.execute(
            "INSERT INTO rubrics (name, context, source, source_path, description, "
            "created_at, domain_id) VALUES (%s,'check','platform-seed',%s,%s,%s,%s) "
            "RETURNING id",
            (RUBRIC_NAME, "scripts/seed_finance_rubric.py",
             "金融事实质量：可回源、可对账、不拿机器草稿当真值",
             now_iso(), domain["id"]),
        ).fetchone()["id"]
    for ordinal, (name, desc, guide) in enumerate(CRITERIA):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (%s,%s,%s,%s,%s)",
            (rubric_id, name, desc, guide, ordinal),
        )
    conn.commit()
    visible = domain_rubrics.effective_rubrics(
        conn, domain_path=domain.get("path") or domain["key"])
    return {"rubric_id": rubric_id, "criteria": len(CRITERIA),
            "visible": [r["name"] for r in visible]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="finance")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import workspaces
    from src.eval.db import connect

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"域 {args.domain!r} 不存在", file=sys.stderr)
            return 1
        print(f"域 {args.domain}（id={domain['id']}）")
        print(f"尺子 {RUBRIC_NAME}：{len(CRITERIA)} 条判据")
        for name, desc, _guide in CRITERIA:
            print(f"  - {name}：{desc}")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        out = seed(conn, domain_key=args.domain)
        print(f"写入 rubric id={out['rubric_id']}，{out['criteria']} 条判据")
        print("该域可见尺子:", out["visible"])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
