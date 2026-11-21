"""给数据本体域建一把「数据集实体声明」尺子（幂等）。

    uv run python scripts/seed_data_ontology_rubric.py --dry-run
    uv run python scripts/seed_data_ontology_rubric.py

为什么是这些判据：这个域的产物是**数据集实体的声明**——「这张表是什么、主键是哪
几列、值域长什么样」。它的质量为题不在描述文字，而在**声明能不能被真实数据核对**。
所以七条全部是机器可判的事实，取自本轮（2026-11-21）对 `wire_datasets` 真行做的
聚合，不是凭空立的标准：

- 主键必须真的唯一（`group_by` 组数 == 行数）；
- 主键列必须都在列快照里（否则声明的是一个不存在的列）；
- 键里不许放被决定的观测时点（`period` 在每个键分组内唯一 ⇒ 它不进键）；
- 身份必须是裸数据集键（`entity:` 前缀会造成同数据集两份单元）；
- 证据必须带可回源的定位（dataset id / 行数 / 列快照）；
- 同一数据集同一主张只留一份声明；
- 关系的两端必须在同域是活实体。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUBRIC_NAME = "dataset-entity-declaration"

#: (名称, 说明, 判定指引)。每条都对应一次可执行的查询或一次可比对的字段。
CRITERIA: list[tuple[str, str, str]] = [
    ("主键真实唯一", "声明的键组合在全表上分组数必须等于行数",
     "对声明的键列做 group_by，组数 == 行数才算成立。少一组就说明该组合不是键，"
     "只是「看起来像键」。只声明单列时同时给出该列的分组数，证明它确实非唯一。"),
    ("主键列在列快照内", "声明的每一个键列都必须出现在该数据集的列清单里",
     "键列不在列快照里，等于声明了一个不存在的列——这类错误在确认时看不出来，"
     "要到下游按该列取数时才炸。"),
    ("键不含被决定的时点列", "在一对键分组内取值唯一的列，是该分组的观测属性，不是身份",
     "实测判据：若 `(a,b)` 已全表唯一，且每个 `(a,b)` 分组内 `t` 只有一个取值，"
     "则 `t` 是被 `(a,b)` 决定的观测时点，不应进主键——否则下一次快照同步会给"
     "每一条记录换一个新身份。"),
    ("身份是裸数据集键", "实体单元的 external_key 必须是数据集键本身",
     "`entity:` 之类的前缀不被归名规则剥离，会成为同一数据集的第二份知识单元。"
     "同一数据集只能有一个实体身份。"),
    ("证据可回源", "证据必须带 dataset id、行数与列快照",
     "三条缺一即不可回源：没有 dataset id 定位不到表、没有行数无法复算唯一性、"
     "没有列快照无法核对键列是否存在。"),
    ("同一数据集同一主张只声明一次", "同 kind + 同数据集 + 同键列，只允许一份声明",
     "两次提交不是互相印证，是把同一条事实写两遍。允许保留证据更完整的一份，"
     "另一份必须被驳回而不是默默共存。"),
    ("关系两端在同域是活实体", "n:1 / 1:n / m:n 的两端都必须在本域有活单元或待确认提案",
     "关系不替实体兜底：端点不存在时确认必然失败。这也是「关系提案的 evidence "
     "必须是带 from_key/to_key 的对象」这条结构要求的下游后果——证据形状不对，"
     "端点根本读不出来。"),
]


def seed(conn: Any, *, domain_key: str) -> dict:
    """写入（或更新）该域的数据集实体声明尺；返回 {rubric_id, criteria, visible}。"""
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
            (RUBRIC_NAME, "scripts/seed_data_ontology_rubric.py",
             "数据集实体声明：主键可复算、证据可回源、身份唯一",
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
    ap.add_argument("--domain", default="data-ontology")
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
        print(f"域 {args.domain}（id={domain['id']}，锚 v{domain['template_version']}）")
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
