#!/usr/bin/env python3
"""Seed the 19 per-contract-type generation (drafting) prompts.

One `draft_<type>` prompt per 《民法典》典型有名合同类型, `purpose = 'drafting'`,
`contract_type` matching the rubric type key (loose coupling - no FK). Each
prompt's `content` is a Chinese drafting instruction tailored to that type's
mandatory clauses, mirroring the per-class rubric themes.

Idempotent: upserts by `name` (UNIQUE) - UPDATE if present, else INSERT with
`source = 'local'`. Re-running never duplicates and never touches `rubrics` or
`criteria`. Note: re-running WILL overwrite a prompt edited through the UI -
same trade-off as seed_contract_rubrics.py / seed_sample_local_rubric.py.

Reuses the schema helpers from extract_harbor_rules so the schema has one
source of truth.

Run:
    uv run python scripts/seed_contract_prompts.py
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root


def upsert_local_prompt(conn: sqlite3.Connection, prompt: dict, now_iso: str) -> int:
    """Upsert a local prompt by `name` (UNIQUE). Returns the prompt id.

    Single-row upsert (no child table): UPDATE the existing row if the name is
    taken, else INSERT. `source` is always 'local'.
    """
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM prompts WHERE name = ?", (prompt["name"],)
    ).fetchone()
    if row:
        pid = row[0]
        cur.execute(
            "UPDATE prompts SET contract_type = ?, purpose = ?, content = ?, "
            "prompt_type = ?, description = ? WHERE id = ?",
            (
                prompt["contract_type"],
                prompt["purpose"],
                prompt["content"],
                prompt.get("prompt_type", "baseline"),
                prompt.get("description"),
                pid,
            ),
        )
    else:
        cur.execute(
            "INSERT INTO prompts (name, contract_type, purpose, content, source, "
            "prompt_type, description, created_at) VALUES (?, ?, ?, ?, 'local', ?, ?, ?)",
            (
                prompt["name"],
                prompt["contract_type"],
                prompt["purpose"],
                prompt["content"],
                prompt.get("prompt_type", "baseline"),
                prompt.get("description"),
                now_iso,
            ),
        )
        pid = cur.lastrowid
    return pid


def _p(type_key: str, description: str, content: str) -> dict:
    return {
        "name": f"draft_{type_key}",
        "contract_type": type_key,
        "purpose": "drafting",
        "description": description,
        "content": content.strip(),
        "prompt_type": "baseline",
    }


# 19 per-type drafting prompts. content = Chinese drafting instructions.
PROMPTS: list[dict] = [
    _p("sale", "买卖合同起草提示词",
       """起草一份买卖合同。须包含：标的物名称、规格、数量与质量标准；价款与支付方式（含定金、尾款节点）；交付时间、地点与方式；所有权转移时点（交付或登记）；毁损灭失风险自交付时转移（或另有约定）；检验期间与质量异议通知方式；瑕疵担保责任及修理/更换/退货/减价救济；违约责任与争议解决。如分期付款，可约定所有权保留并办理登记。"""),
    _p("utilities_supply", "供用电水气热力合同起草提示词",
       """起草一份供用（电/水/气/热力）合同。须包含：供应人与用户信息；供应标的与质量标准；计量方式、单价及结算周期；连续供应义务；中止供应的事由与事先通知义务及合理期限；用户缴费义务与违约责任；争议解决。"""),
    _p("gift", "赠与合同起草提示词",
       """起草一份赠与合同。须包含：赠与人、受赠人信息；赠与财产的名称、数量与状况；交付或登记办理安排（不动产须办登记）；赠与人任意撤销权的条件（交付前、非公证/公益除外）；法定撤销事由与一年除斥期间；如附义务，载明所附义务（不超过赠与财产价值）；违约责任。"""),
    _p("loan", "借款合同起草提示词",
       """起草一份借款合同。须包含：借款人、贷款人信息；借款币种与金额；借款用途及挪用后果；利率（不得超过合同成立时一年期LPR的四倍）；利息支付方式与周期；借款期限与还款方式；提前还款的条件与利息处理；违约责任与争议解决。"""),
    _p("guarantee", "保证合同起草提示词",
       """起草一份保证合同。须包含：保证人、债权人、债务人信息；被担保的主债权种类与数额；保证方式（一般保证或连带责任保证，未约定推定一般保证）；保证范围（主债权及利息、违约金、损害赔偿、实现债权费用）；保证期间与起算时点；主合同变更须经保证人同意及后果；违约责任。"""),
    _p("lease", "租赁合同起草提示词",
       """起草一份租赁合同。须包含：出租人、承租人信息；租赁物名称、数量、用途；租赁期限（不得超过20年，超过部分无效）；租金数额、支付方式与周期；交付与返还状态；维修义务（原则上出租人）；承租人优先承租权（同等条件下）；转租须经出租人同意；违约责任与争议解决。"""),
    _p("financing_lease", "融资租赁合同起草提示词",
       """起草一份融资租赁合同。须包含：出租人、承租人、出卖人信息；租赁物名称、规格与选定；租金构成（购买成本与利润）及支付周期；租赁物所有权归出租人并办理登记（对抗第三人）；租赁物瑕疵与维修责任（多由承租人负担）；期满租赁物归属（留购/续租/返还）；违约责任。"""),
    _p("factoring", "保理合同起草提示词",
       """起草一份保理合同。须包含：保理人、应收账款债权人信息；应收账款描述（金额、基础交易、债务人）；有追索权或无追索权类型；应收账款转让通知债务人的安排；保理服务内容（资金融通/管理/催收/付款担保）；回购或反转让的触发情形与对价；违约责任。"""),
    _p("work", "承揽合同起草提示词",
       """起草一份承揽合同。须包含：定作人、承揽人信息；工作成果名称、规格与技术要求；材料提供方与毁损风险负担；交付时间、地点与验收标准/期限；报酬数额与支付方式；定作人指示变更与协助义务；承揽人留置权（报酬未付时）；违约责任。"""),
    _p("construction", "建设工程合同起草提示词",
       """起草一份建设工程合同。须包含：发包人、承包人信息；工程范围与工期；工程价款与支付节点（预付/进度/结算）及结算方式；竣工验收标准、程序与期限；质量保修范围与保修期；承包人工程价款优先受偿权及行使期限；违约责任与争议解决。"""),
    _p("transport", "运输合同起草提示词",
       """起草一份运输合同。须包含：承运人、旅客/托运人信息；运输标的（货物描述或旅客）与起运地、目的地；运到期限；运费与支付方式；客票/托运单等运输凭证；货物灭失毁损的赔偿标准与限额；承运人免责事由（不可抗力、货物自身性质等）；违约责任。"""),
    _p("technology", "技术合同起草提示词",
       """起草一份技术（开发/转让/咨询/服务）合同。须包含：项目名称与内容；技术成果权属（专利申请权/所有权）归属；保密范围、期限与违约责任；后续改进成果的归属与分享；技术开发风险分担（如适用）；价款或使用费及支付方式；验收标准；违约责任。"""),
    _p("bailment", "保管合同起草提示词",
       """起草一份保管合同。须包含：保管人、寄存人信息；保管物名称、数量与状况；交付与返还时点及状态；保管期间；保管费（有偿/无偿）及支付；赔偿责任标准（有偿重于无偿）；危险保管物的告知义务；违约责任。"""),
    _p("warehousing", "仓储合同起草提示词",
       """起草一份仓储合同。须包含：保管人、存货人信息；仓储物名称、数量与状况；储存期间；入库验收与出库提取程序；仓单签发及必要记载事项；危险物品告知与处置；损害赔偿范围与限额；仓储费及支付；违约责任。"""),
    _p("entrustment", "委托合同起草提示词",
       """起草一份委托合同。须包含：委托人、受托人信息；委托事务范围与代理权限；转委托须经同意及责任承担；受托人报告进度与结果的义务；费用预付/垫付与报酬及支付方式；委托人或受托人的任意解除权及赔偿后果；违约责任。"""),
    _p("property_service", "物业服务合同起草提示词",
       """起草一份物业服务合同。须包含：物业服务人与业主（或业主大会）信息；服务事项、标准与质量要求；物业费项目、标准与收缴方式；服务期限；业主解聘权与程序及提前通知期限；服务终止时的资料、财物交接义务；专项维修资金的筹集与使用；违约责任。"""),
    _p("brokerage", "行纪合同起草提示词",
       """起草一份行纪合同。须包含：委托人、行纪人信息；委托贸易的商品、数量与价格区间；行纪人以自己名义从事贸易及法律后果；低于指定价格卖出或高于指定价格买入的差额补偿或利益归属；行纪人自买自卖的情形与价格条件；报酬数额与支付条件；违约责任。"""),
    _p("intermediation", "中介合同起草提示词",
       """起草一份中介合同。须包含：委托人、中介人信息；中介服务内容（报告订约机会或提供媒介服务）；中介人如实报告重要事项的义务及隐瞒责任；报酬数额与支付条件（以促成合同成立为条件）；未促成时中介活动费用的承担；违约责任。"""),
    _p("partnership", "合伙合同起草提示词",
       """起草一份合伙合同。须包含：合伙人信息；合伙目的与事业；出资方式（货币/实物/劳务等）与数额；利润分配与亏损分担比例；合伙事务执行人与决策/表决规则；入伙的同意条件与退伙的结算方式；解散事由与清算程序；违约责任。"""),
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=project_root() / DEFAULT_DB)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        create_schema(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        for prompt in PROMPTS:
            pid = upsert_local_prompt(conn, prompt, now_iso)
            print(f"  upserted {prompt['name']:24} [{prompt['contract_type']:18}] (prompt_id={pid})")
        conn.commit()
        print(f"\nSeeded {len(PROMPTS)} per-type drafting prompts into {args.db}")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
