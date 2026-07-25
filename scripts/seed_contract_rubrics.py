#!/usr/bin/env python3
"""Seed the 19 per-class Chinese contract evaluation rubrics.

One rubric per 《民法典》典型有名合同类型 (买卖、供用电水气热力、赠与、借款、保证、
租赁、融资租赁、保理、承揽、建设工程、运输、技术、保管、仓储、委托、物业服务、
行纪、中介、合伙). Each rubric = the 4 shared base criteria + 4-6 type-specific
criteria drawn from that type's 民法典 mandatory-clause set; all criteria are written
in Chinese (description = the check, guidance = PASS if … / FAIL if …).

Idempotent: re-running upserts by (name, source='local') and never duplicates.
Harbor rubrics (source LIKE 'harbor:%') and the sample local rubric
(`contract_drafting_v1`) are never touched - upsert matches on source='local' only.

Reuses `upsert_local_rubric` from seed_sample_local_rubric and the schema helpers
from extract_harbor_rules so the schema has one source of truth.

Run:
    uv run python scripts/seed_contract_rubrics.py
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root
from seed_sample_local_rubric import upsert_local_rubric


# 4 shared base criteria - apply to every contract type. Chinese check/guidance.
BASE_CRITERIA: list[dict[str, str]] = [
    {
        "name": "party_identification",
        "description": "是否清晰识别全部合同主体，载明完整法律名称与角色（甲方/乙方）？",
        "guidance": "PASS if 每一方均以完整法律主体名称列明并标注角色；FAIL if 任一主体未列明、表述含糊或仅以代词指代。",
    },
    {
        "name": "governing_law_present",
        "description": "是否明确约定适用法律（如中华人民共和国法律）？",
        "guidance": "PASS if 适用法律条款明确列明管辖法域；FAIL if 缺失或仅作隐含约定。",
    },
    {
        "name": "clause_completeness",
        "description": "是否具备该类合同的必备条款（如违约责任、争议解决、合同期限等）？",
        "guidance": "PASS if 该合同类型标准必备条款齐备；FAIL if 任一必备条款缺失。",
    },
    {
        "name": "legal_citation_accuracy",
        "description": "法条引用是否准确且现行有效（如《民法典》条文序号）？",
        "guidance": "PASS if 所引法律真实存在且条文序号准确；FAIL if 引用系编造、已废止或序号错误。",
    },
]


def _c(name: str, description: str, guidance: str) -> dict[str, str]:
    return {"name": name, "description": description, "guidance": guidance}


def _rubric(type_key: str, description: str, extra: list[dict[str, str]]) -> dict:
    return {
        "name": f"contract_{type_key}_v1",
        "context": "contract",
        "description": description,
        "criteria": BASE_CRITERIA + extra,
    }


# 19 per-class rubrics. type-specific criteria from each type's 民法典 mandatory set.
RUBRICS: list[dict] = [
    _rubric("sale", "买卖合同评价规则：标的物所有权转移、风险转移、检验与瑕疵担保。",
        [
            _c("ownership_transfer", "是否约定标的物所有权转移的时点（交付或登记）？",
               "PASS if 所有权转移时点明确（交付时或另有约定）；FAIL if 未约定导致权属不清。"),
            _c("risk_transfer_point", "是否明确标的物毁损灭失风险的转移时点？",
               "PASS if 风险自交付时转移（或约定其他时点）并载明；FAIL if 风险负担约定缺失。"),
            _c("inspection_period", "是否约定检验期间与质量异议期限？",
               "PASS if 检验期间及异议通知方式明确；FAIL if 未约定检验期导致视为合格不明。"),
            _c("defect_warranty", "是否约定质量瑕疵担保责任与救济方式？",
               "PASS if 瑕疵担保责任及修理/更换/退货/减价等救济明确；FAIL if 瑕疵救济缺失。"),
            _c("ownership_retention", "所有权保留条款是否合法且表述清晰（如分期付款）？",
               "PASS if 所有权保留约定清晰且经登记可对抗第三人（如适用）；FAIL if 约定模糊或损害买受人法定权利。"),
        ]),
    _rubric("utilities_supply", "供用电、水、气、热力合同评价规则：中止供应、计量与连续供应义务。",
        [
            _c("suspension_notice", "是否约定中止供应的事由与事先通知义务？",
               "PASS if 中止供应须事先通知并载明合理期限；FAIL if 可任意中止且无通知义务。"),
            _c("metering_and_pricing", "是否明确计量方式、价格与结算周期？",
               "PASS if 计量方法、单价及结算周期清晰；FAIL if 计量或计价约定不明。"),
            _c("continuous_supply", "是否约定连续供应义务与中断赔偿责任？",
               "PASS if 供应人负连续供应义务并约定中断时的责任；FAIL if 连续性义务及责任缺失。"),
        ]),
    _rubric("gift", "赠与合同评价规则：撤销权、交付登记与附义务赠与。",
        [
            _c("arbitrary_revocation", "是否界定赠与人任意撤销权的行使条件与除外情形？",
               "PASS if 任意撤销权条件（交付前、非公证/公益）表述正确；FAIL if 撤销条件违法或缺失。"),
            _c("statutory_revocation", "是否列明法定撤销权的事由（如受赠人侵害赠与人）？",
               "PASS if 法定撤销事由与一年除斥期间载明；FAIL if 法定撤销事由遗漏。"),
            _c("delivery_or_registration", "是否明确赠与物交付或登记的办理安排？",
               "PASS if 需登记的赠与（如不动产）约定登记办理；FAIL if 应登记而未约定登记。"),
            _c("conditional_gift", "附义务赠与是否载明所附义务及其限度？",
               "PASS if 所附义务清晰且不超过赠与财产价值；FAIL if 义务约定不清或显失公平。"),
        ]),
    _rubric("loan", "借款合同评价规则：利率上限、利息支付与借款用途。",
        [
            _c("interest_rate_cap", "利率是否未超过司法保护上限（合同成立时一年期LPR的四倍）？",
               "PASS if 约定利率≤LPR四倍；FAIL if 超过司法保护上限（高利贷风险）。"),
            _c("interest_payment", "是否明确利息支付方式与周期？",
               "PASS if 利率、付息周期与方式清晰；FAIL if 利息支付约定不明。"),
            _c("early_repayment", "是否约定提前还款的条件与利息计算？",
               "PASS if 提前还款的通知与利息处理明确；FAIL if 提前还款规则缺失。"),
            _c("loan_purpose", "是否约定借款用途及挪用后果？",
               "PASS if 借款用途明确并约定违约后果；FAIL if 用途不明或无挪用约束。"),
        ]),
    _rubric("guarantee", "保证合同评价规则：保证方式、期间、范围与主合同变更。",
        [
            _c("guarantee_type", "是否明确保证方式（一般保证或连带责任保证）？",
               "PASS if 保证方式明确约定（未约定推定一般保证）；FAIL if 方式不清导致争议。"),
            _c("guarantee_period", "是否约定保证期间及其起算？",
               "PASS if 保证期间长度与起算时点明确；FAIL if 保证期间缺失（视为法定）。"),
            _c("guarantee_scope", "是否明确保证范围（主债权、利息、违约金、损害赔偿、实现债权费用）？",
               "PASS if 保证范围列明完整；FAIL if 范围约定不全。"),
            _c("master_contract_change", "是否约定主合同变更对保证责任的影响？",
               "PASS if 主合同变更须经保证人同意及后果载明；FAIL if 变更影响未约定。"),
        ]),
    _rubric("lease", "租赁合同评价规则：租期上限、租金、优先承租权与维修义务。",
        [
            _c("lease_term_cap", "租赁期限是否≤20年（超过部分无效）？",
               "PASS if 约定租期≤20年；FAIL if 约定超过20年（超过部分无效）。"),
            _c("rent_and_payment", "是否明确租金数额、支付方式与周期？",
               "PASS if 租金、付租周期与支付方式清晰；FAIL if 租金或支付约定不明。"),
            _c("priority_renewal", "是否约定承租人优先承租权（同等条件下）？",
               "PASS if 期满续租的优先权及条件载明；FAIL if 优先承租权缺失。"),
            _c("maintenance_duty", "是否明确维修义务的承担方？",
               "PASS if 维修义务归属明确（原则上出租人）；FAIL if 维修责任约定不明。"),
            _c("subletting_restriction", "是否约定转租的限制与同意要件？",
               "PASS if 转租须经出租人同意及后果载明；FAIL if 转租规则缺失。"),
        ]),
    _rubric("financing_lease", "融资租赁合同评价规则：所有权登记、租金构成与期满归属。",
        [
            _c("ownership_and_registration", "是否明确租赁物所有权归属与登记安排？",
               "PASS if 所有权归出租人并约定登记（对抗第三人）；FAIL if 权属或登记约定不清。"),
            _c("rent_composition", "是否明确租金构成（含购买成本与利润）及支付？",
               "PASS if 租金构成与支付周期清晰；FAIL if 租金构成不明。"),
            _c("defect_and_maintenance", "是否约定租赁物瑕疵与维修责任的承担？",
               "PASS if 瑕疵担保与维修责任归属明确（多由承租人负担）；FAIL if 责任约定不明。"),
            _c("end_of_term_ownership", "是否约定期满租赁物的归属？",
               "PASS if 期满归属（留购/续租/返还）明确；FAIL if 期满归属未约定。"),
        ]),
    _rubric("factoring", "保理合同评价规则：应收账款转让通知、追索权与回购。",
        [
            _c("assignment_notice", "是否约定应收账款转让通知债务人的安排？",
               "PASS if 转让通知主体与方式明确；FAIL if 通知安排缺失（对债务人不生效）。"),
            _c("recourse_type", "是否明确有追索权或无追索权保理类型？",
               "PASS if 追索权类型清晰界定；FAIL if 追索权约定不明。"),
            _c("receivables_description", "应收账款的描述是否清晰可识别？",
               "PASS if 应收账款金额、基础交易与债务人列明；FAIL if 标的应收账款描述不清。"),
            _c("buyback_or_retransfer", "是否约定回购或反转让的情形与对价？",
               "PASS if 回购/反转让触发情形与对价明确；FAIL if 回购安排缺失。"),
        ]),
    _rubric("work", "承揽合同评价规则：成果交付验收、材料提供与留置权。",
        [
            _c("delivery_and_acceptance", "是否约定工作成果的交付与验收标准？",
               "PASS if 交付时间、地点与验收标准/期限明确；FAIL if 验收约定缺失。"),
            _c("materials_and_risk", "是否明确材料提供方与毁损风险负担？",
               "PASS if 材料（承揽人/定作人提供）及风险归属载明；FAIL if 材料与风险约定不明。"),
            _c("instructions_and_assistance", "是否约定定作人的指示与协助义务？",
               "PASS if 定作人指示变更与协助义务载明；FAIL if 协助义务缺失。"),
            _c("lien_right", "是否约定承揽人对工作成果的留置权？",
               "PASS if 报酬未付时的留置权及实现方式载明；FAIL if 留置权约定缺失。"),
        ]),
    _rubric("construction", "建设工程合同评价规则：工程范围、竣工验收、结算与保修。",
        [
            _c("scope_and_schedule", "是否明确工程范围与工期？",
               "PASS if 工程范围、工期及延期责任明确；FAIL if 范围或工期约定不明。"),
            _c("completion_acceptance", "是否约定竣工验收程序与标准？",
               "PASS if 竣工验收标准、程序与期限载明；FAIL if 验收约定缺失。"),
            _c("payment_and_settlement", "是否约定工程款支付节点与结算方式？",
               "PASS if 预付/进度/结算款节点与结算方式清晰；FAIL if 付款节点不明。"),
            _c("quality_warranty", "是否约定质量保修范围与保修期？",
               "PASS if 保修范围、保修期与责任载明；FAIL if 保修条款缺失。"),
            _c("priority_of_payment", "是否提示承包人工程价款优先受偿权？",
               "PASS if 优先受偿权及行使期限（合理期限）载明；FAIL if 优先权约定缺失。"),
        ]),
    _rubric("transport", "运输合同评价规则：运输标的、运到期限与赔偿免责。",
        [
            _c("subject_and_deadline", "是否明确运输标的与运到期限？",
               "PASS if 货物/旅客描述与运到期限明确；FAIL if 标的或期限约定不明。"),
            _c("ticket_or_waybill", "是否约定客票/托运单等运输凭证？",
               "PASS if 运输凭证的出具与效力载明；FAIL if 凭证约定缺失。"),
            _c("loss_or_damage_compensation", "是否约定货物灭失毁损的赔偿标准？",
               "PASS if 赔偿限额/计算方式与归责原则载明；FAIL if 赔偿约定不明。"),
            _c("exemptions", "是否列明承运人免责事由？",
               "PASS if 法定免责事由（不可抗力、货物自身性质等）载明；FAIL if 免责事由缺失。"),
        ]),
    _rubric("technology", "技术合同评价规则：成果权属、保密、后续改进与风险分担。",
        [
            _c("result_ownership", "是否明确技术成果的权属归属？",
               "PASS if 技术成果权属（专利申请权/所有权）明确；FAIL if 权属约定不明。"),
            _c("confidentiality", "是否约定保密义务与期限？",
               "PASS if 保密范围、期限与违约责任载明；FAIL if 保密条款缺失。"),
            _c("subsequent_improvement", "是否约定后续改进成果的归属与分享？",
               "PASS if 后续改进的权属与分享方式明确；FAIL if 改进归属未约定。"),
            _c("development_risk", "技术开发是否约定风险分担？",
               "PASS if 开发失败风险的分担与通知义务载明；FAIL if 风险分担缺失（技术开发合同）。"),
            _c("price_or_royalty", "是否明确价款或使用费及支付方式？",
               "PASS if 价款/使用费数额与支付方式清晰；FAIL if 报酬约定不明。"),
        ]),
    _rubric("bailment", "保管合同评价规则：保管物交付返还、期间与赔偿责任。",
        [
            _c("delivery_and_return", "是否约定保管物的交付与返还？",
               "PASS if 交付、返还时点与状态明确；FAIL if 交付返还约定不明。"),
            _c("custody_period", "是否约定保管期间？",
               "PASS if 保管期间及起止明确；FAIL if 期间约定不明。"),
            _c("liability_paid_vs_free", "是否有偿保管是否明确赔偿责任标准？",
               "PASS if 有偿/无偿保管的责任轻重区分并载明；FAIL if 赔偿责任标准缺失。"),
            _c("danger_notice", "是否约定危险保管物的告知义务？",
               "PASS if 危险保管物（易燃易爆等）的告知义务载明；FAIL if 危险告知缺失。"),
        ]),
    _rubric("warehousing", "仓储合同评价规则：仓单、储存期间与赔偿限额。",
        [
            _c("warehouse_receipt", "是否约定仓单的签发与记载事项？",
               "PASS if 仓单签发及必要记载事项载明；FAIL if 仓单约定缺失。"),
            _c("storage_period", "是否明确储存期间？",
               "PASS if 储存期间及起止明确；FAIL if 储存期间约定不明。"),
            _c("extraction_and_inspection", "是否约定提取与验收安排？",
               "PASS if 入库验收与出库提取的程序载明；FAIL if 验收提取约定缺失。"),
            _c("dangerous_goods_notice", "是否约定危险物品的告知与处理？",
               "PASS if 危险物品告知义务及处置载明；FAIL if 危险品告知缺失。"),
            _c("compensation_limit", "是否约定赔偿范围与限额？",
               "PASS if 损害赔偿计算与限额明确；FAIL if 赔偿约定不明。"),
        ]),
    _rubric("entrustment", "委托合同评价规则：事务权限、转委托、报告与任意解除。",
        [
            _c("affairs_and_authority", "是否明确委托事务范围与权限？",
               "PASS if 委托事务范围与代理权限清晰；FAIL if 事务或权限约定不明。"),
            _c("sub_entrustment", "是否约定转委托的条件？",
               "PASS if 转委托须经同意及责任承担载明；FAIL if 转委托规则缺失。"),
            _c("reporting_duty", "是否约定受托人的报告义务？",
               "PASS if 报告进度与结果的义务载明；FAIL if 报告义务缺失。"),
            _c("expenses_and_remuneration", "是否明确费用与报酬？",
               "PASS if 费用预付/垫付与报酬及支付方式清晰；FAIL if 费用报酬约定不明。"),
            _c("arbitrary_termination", "是否提示委托人或受托人的任意解除权？",
               "PASS if 任意解除权及赔偿后果载明；FAIL if 解除权约定缺失。"),
        ]),
    _rubric("property_service", "物业服务合同评价规则：服务标准、收费、解聘与交接。",
        [
            _c("service_scope_and_standard", "是否明确服务内容与标准？",
               "PASS if 服务事项、标准与质量要求载明；FAIL if 服务标准约定不明。"),
            _c("fees", "是否约定收费项目、标准与收缴方式？",
               "PASS if 物业费项目、标准与收缴方式清晰；FAIL if 收费约定不明。"),
            _c("owner_termination_right", "是否提示业主的解聘权与程序？",
               "PASS if 业主解聘程序与提前通知期限载明；FAIL if 解聘权约定缺失。"),
            _c("handover", "是否约定服务终止时的交接义务？",
               "PASS if 资料、财物交接义务与期限载明；FAIL if 交接约定缺失。"),
            _c("special_repair_fund", "是否涉及专项维修资金的筹集与使用？",
               "PASS if 专项维修资金使用范围与程序载明（如适用）；FAIL if 应约定而未约定。"),
        ]),
    _rubric("brokerage", "行纪合同评价规则：自有名义、价格差额与买受出卖义务。",
        [
            _c("own_name_trade", "是否明确行纪人以自己名义从事贸易？",
               "PASS if 行纪人自有名义交易及法律后果载明；FAIL if 名义约定不明。"),
            _c("price_difference", "是否约定低于指定价格卖出或高于指定价格买入的差额补偿？",
               "PASS if 价格差额的补偿或利益归属载明；FAIL if 差额规则缺失。"),
            _c("buy_or_sell_obligation", "是否约定行纪人买受/出卖义务的触发情形？",
               "PASS if 行纪人自买自卖的情形与价格条件载明；FAIL if 买受出卖规则缺失。"),
            _c("remuneration", "是否明确报酬及支付条件？",
               "PASS if 报酬数额与支付条件清晰；FAIL if 报酬约定不明。"),
        ]),
    _rubric("intermediation", "中介合同评价规则：报告媒介义务、如实报告与报酬条件。",
        [
            _c("report_or_intermediation_duty", "是否明确报告订约机会或媒介服务的义务？",
               "PASS if 报告/媒介服务内容明确；FAIL if 服务义务约定不明。"),
            _c("truthful_report", "是否约定如实报告义务？",
               "PASS if 如实报告重要事项及隐瞒责任载明；FAIL if 如实报告义务缺失。"),
            _c("remuneration_condition", "是否明确报酬支付条件（促成合同成立）？",
               "PASS if 报酬以促成合同成立为条件并载明；FAIL if 报酬条件约定不明。"),
            _c("expense_bearing", "是否约定中介活动费用的承担？",
               "PASS if 中介费用承担方明确（未促成时）；FAIL if 费用承担约定缺失。"),
        ]),
    _rubric("partnership", "合伙合同评价规则：出资、利润亏损分担与解散清算。",
        [
            _c("capital_contribution", "是否明确合伙人的出资方式与数额？",
               "PASS if 出资方式（货币/实物/劳务等）与数额载明；FAIL if 出资约定不明。"),
            _c("profit_and_loss_sharing", "是否约定利润分配与亏损分担比例？",
               "PASS if 利润分配与亏损分担比例明确；FAIL if 分配比例约定不明。"),
            _c("partnership_affairs", "是否约定合伙事务的执行与决策？",
               "PASS if 事务执行人及表决/决策规则载明；FAIL if 事务执行约定不明。"),
            _c("admission_and_withdrawal", "是否约定入伙与退伙的条件？",
               "PASS if 入伙同意条件与退伙结算方式载明；FAIL if 入伙退伙规则缺失。"),
            _c("dissolution_and_liquidation", "是否约定解散事由与清算方式？",
               "PASS if 解散事由与清算程序载明；FAIL if 清算约定缺失。"),
        ]),
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
        for rubric in RUBRICS:
            rid = upsert_local_rubric(conn, rubric, now_iso)
            print(f"  upserted {rubric['name']:34} -> {len(rubric['criteria'])} criteria (rubric_id={rid})")
        conn.commit()
        print(f"\nSeeded {len(RUBRICS)} per-class contract rubrics into {args.db}")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
