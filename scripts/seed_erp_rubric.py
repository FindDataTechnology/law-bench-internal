"""给 ERP 域建一把「账本体一致性」尺子（幂等）。

    uv run python scripts/seed_erp_rubric.py --dry-run
    uv run python scripts/seed_erp_rubric.py

为什么是这些判据：ERP 域的产物不是文本，是**账与映射**。它的质量为题不在措辞，
而在「本体里的每一条断言是否站得住」——所以八条全部是**可机器核对的事实**，不请
模型打印象分。判据取自两个已在跑的来源，不新造标准：

- `fd-erp-vertical-templates/README.md` 的四条边界铁律（`boundary.py` 机械化审计）
- `fd-erp-ledger-mcp` 的科目预设与 proposal→确认门纪律

这八条直接支撑该域的三项下游用途：映射可信（1/2/3）、账不经旁路（4/5/6）、
外部系统没接通时不说接通（7/8）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUBRIC_NAME = "erp-ontology-consistency"

#: (名称, 说明, 判定指引)。
CRITERIA: list[tuple[str, str, str]] = [
    ("映射本端存在", "每条映射指向的本端实体必须在本域真实存在",
     "crosswalk 的 external_key 是 `<类型>:<键>`；键那一半必须在本域活单位里，"
     "或在本域待确认提案里。悬空即不通过——它不是「外部系统没接通」，是本域少了一条实体。"),
    ("映射目标在通用科目闭集内", "行业科目只能映到内核通用科目",
     "maps_to 的目标必须是 universal_accounts 预设内的编码（本轮 12 码）。指向预设外的"
     "编码即不通过：那是一条会被查询时才炸的承诺。"),
    ("映射不冒充已复核", "没有置信度的映射不得计入覆盖率",
     "缺 confidence 视为未复核（fail closed）。允许存在，但读面必须标「待复核」，"
     "且不计入映射覆盖率的分子。"),
    ("账务事实只在内核", "模板层与域内不得存任何账务事实",
     "本域知识单元里不应出现余额、分录、科目余额表这类账务结果。出现即不通过："
     "账务事实的唯一载体是内核账本，域里存一份就是第二份会漂移的真源。"),
    ("回写只出 proposal", "对账结论只能以待确认形态回写",
     "任何回写必须以 proposal（pending）形态存在，且确认门只属拍板席位。"
     "出现直写落账的路径即不通过。"),
    ("回写科目在车道白名单内", "机器车道不能写资金类科目",
     "回写的科目限应收/在途/收入/费用；资金类分录禁入机器车道。越界即不通过。"),
    ("外部系统接通以三态为准", "catalog / executor_tests / live 三态全齐才可声明接通",
     "任缺一态即报「未接通（缺 X）」，不得以其余两态通过推断接通。"
     "证据过期按缺失处理，不得静默沿用旧证据。"),
    ("模板声明的尺子必须解析得到", "锚定模板的 rubric_refs 不得为空或解析不到",
     "声明的每一条尺子都必须解析到本域可用的 rubric。为空即「模板不可评」，"
     "声明了却解析不到即「承诺了却兑现不了」——两者都不通过。"),
]


def seed(conn: Any, *, domain_key: str) -> dict:
    """写入（或更新）该域的账本体一致性尺；返回 {rubric_id, criteria, visible}。"""
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
            (RUBRIC_NAME, "scripts/seed_erp_rubric.py",
             "ERP 域账本体一致性：映射可信、账不经旁路、接通状态如实",
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
    ap.add_argument("--domain", default="erp")
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
