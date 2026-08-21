"""Slot ontology for contract clauses.

A *slot* is a ``{{name}}`` placeholder. The corpus uses ~7600 distinct slot
names, but only ~270 high-frequency *concepts* (address, phone, name, agent,
legal_rep, bank, account, seal, sign, delivery_date, ...), each with systematic
role-prefix variants (``party_a_address`` / ``seller_address`` / ``buyer_address``
/ ``lessor_address`` ...).

This module is the single source of truth for the canonical concept names, the
variant aliases that map to them, and a slot instruction (label / description /
example / required) for each. It powers two things:

1. **Normalization on write** - :func:`canonicalize_slot` rewrites a variant
   slot name to its canonical form so the corpus stays name-consistent (no
   ``{{seller_name}}`` vs ``{{party_a}}`` for the same concept).
2. **Instruction coverage** - :func:`instruction_for_slot` returns an
   instruction for any known slot, so the coherence gate's "every slot must be
   instructed" check passes for real contracts.

The 12 core slots (``REQUIRED_SLOTS``) keep the hand-written instructions from
:mod:`src.contracts.slots`; extended concepts carry registry instructions here.
The long tail of single-occurrence slots is intentionally not covered - if such
a slot appears without a clause-declared instruction, the coherence gate
surfaces it as data debt.
"""

from __future__ import annotations

import re

from src.contracts.slots import (
    default_slot_instructions,
    latin_to_chinese_map,
    required_slots_for_type,
    REQUIRED_SLOTS,
)

_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")

# ---------------------------------------------------------------------------
# Concept registry
# ---------------------------------------------------------------------------
# Each entry: canonical_name -> {label, description, example, required, aliases}
# `aliases` lists other slot names (role-prefixed or synonym) that map here.
# Role-prefixed variants (seller_X, buyer_X, lessor_X, ...) are ALSO resolved by
# the role-alias table below, so they need not be enumerated per concept.

_CONCEPTS: dict[str, dict] = {
    # --- party identity (core) ---
    "party_a": {"label": "甲方名称", "description": "合同甲方（通常为标的提供方/服务方）的全称或姓名", "example": "北京甲科技有限公司", "required": True,
                "aliases": ["甲方名称", "出卖人", "卖方", "甲方"]},
    "party_b": {"label": "乙方名称", "description": "合同乙方的全称或姓名", "example": "北京乙贸易有限公司", "required": True,
                "aliases": ["乙方名称", "买受人", "买方", "乙方"]},
    # --- party contact / identity details (role-prefixed: party_a_address etc.) ---
    "address": {"label": "联系地址", "description": "当事人的联系地址或住所地", "example": "北京市朝阳区xx路xx号", "required": False, "aliases": []},
    "phone": {"label": "联系电话", "description": "当事人的联系电话", "example": "010-12345678", "required": False, "aliases": ["telephone", "tel", "mobile", "contact_phone"]},
    "email": {"label": "电子邮箱", "description": "当事人的电子邮箱", "example": "contact@example.com", "required": False, "aliases": ["e_mail", "mail"]},
    "zip": {"label": "邮政编码", "description": "当事人的邮政编码", "example": "100000", "required": False, "aliases": ["postal_code", "postcode", "zip_code"]},
    "contact": {"label": "联系方式", "description": "当事人的联系方式", "example": "010-12345678", "required": False, "aliases": ["contact_info", "contact_method"]},
    "agent": {"label": "委托代理人", "description": "当事人的委托代理人姓名", "example": "王某某", "required": False, "aliases": ["authorized_agent", "representative_agent", "agent_name"]},
    "legal_rep": {"label": "法定代表人", "description": "当事人的法定代表人姓名", "example": "李某某", "required": False, "aliases": ["legal_representative", "rep", "representative", "legal_person"]},
    "bank": {"label": "开户银行", "description": "当事人的开户银行名称", "example": "中国工商银行北京xx支行", "required": False, "aliases": ["bank_name", "opening_bank"]},
    "account": {"label": "银行账号", "description": "当事人的银行账号", "example": "6222xxxxxxxxxxxx", "required": False, "aliases": ["account_number", "account_name", "bank_account"]},
    "credit_code": {"label": "统一社会信用代码", "description": "当事人的统一社会信用代码/工商登记注册号", "example": "91110000XXXXXXXXXX", "required": False, "aliases": ["credit_code_no", "social_credit_code", "tax_id", "tax_number"]},
    "id_number": {"label": "证件号码", "description": "当事人的身份证件号码", "example": "110101199001011234", "required": False, "aliases": ["id", "id_no", "identity_number"]},
    "id_type": {"label": "证件类型", "description": "当事人的证件类型", "example": "居民身份证", "required": False, "aliases": []},
    "seal": {"label": "印章", "description": "当事人盖章/公章", "example": "（公章）", "required": False, "aliases": ["seal_name"]},
    "sign": {"label": "签字", "description": "当事人签字", "example": "（签字）", "required": False, "aliases": ["signature"]},
    # --- subject / commercial terms ---
    "subject": {"label": "合同标的", "description": "本合同的具体标的、事宜或范围描述", "example": "买卖合同的具体标的与内容", "required": True, "aliases": ["subject_name", "project_name", "target"]},
    "quantity": {"label": "数量", "description": "标的物数量", "example": "100", "required": False, "aliases": ["amount_quantity", "subject_quantity"]},
    "unit_price": {"label": "单价", "description": "标的物单价", "example": "1000", "required": False, "aliases": ["price", "unit_amount"]},
    "total_amount": {"label": "总价款", "description": "标的物总价款（数字）", "example": "100000", "required": False, "aliases": ["total_price", "sum_amount"]},
    "amount": {"label": "价款金额", "description": "合同价款或费用金额（数字）", "example": "100000", "required": True, "aliases": ["price_amount", "fee"]},
    "deposit_amount": {"label": "定金/保证金", "description": "定金或保证金数额", "example": "10000", "required": False, "aliases": ["deposit", "earnest_money", "guarantee_deposit"]},
    "payment_method": {"label": "付款方式", "description": "价款支付方式", "example": "银行转账", "required": False, "aliases": ["pay_method", "payment"]},
    # --- term / delivery ---
    "term_start": {"label": "履行起始日期", "description": "合同履行开始日期", "example": "2026-01-01", "required": True, "aliases": ["start_date", "effective_date"]},
    "term_end": {"label": "履行结束日期", "description": "合同履行结束日期", "example": "2026-12-31", "required": False, "aliases": ["end_date", "expiry_date", "term_end_month"]},
    "delivery_date": {"label": "交付日期", "description": "标的物交付日期", "example": "2026-06-30", "required": False, "aliases": ["deliver_date", "delivery_time"]},
    "delivery_location": {"label": "交付地点", "description": "标的物交付地点", "example": "北京市朝阳区xx仓库", "required": False, "aliases": ["delivery_place", "delivery_point", "deliver_location"]},
    "delivery_method": {"label": "交付方式", "description": "标的物交付方式", "example": "汽运", "required": False, "aliases": ["deliver_method"]},
    # --- breach / dispute ---
    "penalty": {"label": "违约金", "description": "违约金数额或计算方式", "example": "合同价款的10%", "required": False, "aliases": ["penalty_amount", "liquidated_damages", "breach_penalty"]},
    "penalty_rate": {"label": "违约金比例", "description": "违约金比例", "example": "10%", "required": False, "aliases": ["breach_ratio", "penalty_ratio"]},
    "jurisdiction": {"label": "争议解决方式", "description": "争议解决方式及管辖/仲裁机构", "example": "提交原告所在地人民法院诉讼解决", "required": False, "aliases": ["dispute_resolution_method", "dispute_resolution"]},
    "arbitration_commission": {"label": "仲裁委员会", "description": "约定的仲裁委员会名称", "example": "北京仲裁委员会", "required": False, "aliases": ["arbitration", "arb_commission"]},
    # --- signing ---
    "sign_date": {"label": "签署日期", "description": "合同签署日期", "example": "2026-01-01", "required": True, "aliases": ["sign_date_a", "sign_date_b", "signing_date", "date"]},
    "sign_location": {"label": "签署地点", "description": "合同签署地点", "example": "北京市朝阳区", "required": False, "aliases": ["sign_place", "signing_location"]},
    "sign_month": {"label": "签署月份", "description": "合同签署月份", "example": "1", "required": False, "aliases": []},
    "sign_day": {"label": "签署日", "description": "合同签署日（日）", "example": "15", "required": False, "aliases": []},
    "contract_copies": {"label": "合同份数", "description": "合同一式几份", "example": "一式两份", "required": False, "aliases": ["copies", "copy_count", "contract_copy"]},
    "quality_standard": {"label": "质量标准", "description": "标的物质量标准", "example": "符合国家标准GB/T xxx", "required": False, "aliases": ["quality", "quality_requirement"]},
}

# --- role prefix synonyms -> canonical party_a / party_b ----------------------
# Applied to role-prefixed compound slots, e.g. seller_address -> party_a_address
# for sale. A role maps to party_a or party_b per contract type; types not listed
# fall back to the generic ROLE_TO_PARTY map (seller/lessor/licensor/employer/
# principal -> party_a; buyer/lessee/licensee/employee -> party_b).
_ROLE_TO_PARTY_A = {"seller", "出卖人", "卖方", "供货", "供货方", "订货", "收购", "销售",
                    "lessor", "出租人", "licensor", "许可方", "employer", "用人单位", "甲方",
                    "principal", "委托人", "bailor", "寄存人", "consignor", "发货人",
                    "licensor_a", "seller_a", "a"}
_ROLE_TO_PARTY_B = {"buyer", "买受人", "买方", "lessee", "承租人", "licensee", "被许可方",
                    "employee", "劳动者", "乙方", "agent", "受托人", "bailee", "保管人",
                    "consignee", "收货人", "buyer_b", "b", "licensee_b"}

_ROLE_PREFIXES = sorted(
    set(_ROLE_TO_PARTY_A) | set(_ROLE_TO_PARTY_B) | {"party_a", "party_b", "seller_a", "seller_b", "buyer_a", "buyer_b"},
    key=len, reverse=True,
)


def _strip_role(slot: str) -> tuple[str | None, str]:
    """Return (role, rest) if slot is role-prefixed, else (None, slot)."""
    for r in _ROLE_PREFIXES:
        if slot == r:
            return r, ""
        if slot.startswith(r + "_"):
            return r, slot[len(r) + 1:]
    return None, slot


def _role_to_canonical(role: str | None, contract_type: str | None) -> str | None:
    if role is None:
        return None
    if role in ("party_a", "seller_a"):
        return "party_a"
    if role in ("party_b", "buyer_b"):
        return "party_b"
    if role in _ROLE_TO_PARTY_A:
        return "party_a"
    if role in _ROLE_TO_PARTY_B:
        return "party_b"
    return None


# Stems that mean "the party's name" -> resolve to the bare party slot.
_NAME_STEMS = {"name", "names", "full_name", "company_name", "unit_name", "entity_name"}


def _canonical_concept(rest: str) -> str | None:
    """Map a concept stem (after role stripped) to its canonical concept name."""
    if rest in _CONCEPTS:
        return rest
    for canon, meta in _CONCEPTS.items():
        if rest in meta.get("aliases", []):
            return canon
    return None


def canonicalize_slot(slot: str, contract_type: str | None = None) -> str:
    """Rewrite a variant slot name to its canonical form.

    Examples (sale): ``seller_name`` -> ``party_a``, ``buyer_address`` ->
    ``party_b_address``, ``legal_representative`` -> ``legal_rep``,
    ``party_a_legal_representative`` -> ``party_a_legal_rep``,
    ``party_a_tax_id`` -> ``party_a_credit_code``. Unknown slots are returned
    unchanged.
    """
    s = slot.strip()
    if s in REQUIRED_SLOTS:
        return s
    # full-form (non-role) synonym: legal_representative -> legal_rep
    for canon, meta in _CONCEPTS.items():
        if s in meta.get("aliases", []):
            return canon
    if s in _CONCEPTS:
        return s
    # role-prefixed compound: seller_address, party_a_phone, party_a_tax_id
    role, rest = _strip_role(s)
    if role is not None and rest:
        canon_role = _role_to_canonical(role, contract_type)
        if canon_role is None:
            return s  # unknown role - leave unchanged
        if rest in _NAME_STEMS:
            return canon_role  # party_a_name -> party_a
        concept = _canonical_concept(rest)
        if concept:
            return f"{canon_role}_{concept}"
    return s


def instruction_for_slot(slot: str, contract_type: str | None = None) -> dict | None:
    """Return a slot instruction dict for ``slot`` (canonicalized), or None.

    Returns the **Latin canonical** name so DB writes and the coherence gate
    stay name-consistent. The Chinese display render is a separate output step
    (:func:`render_body_chinese` / :func:`render_instructions_chinese`).
    """
    canon = canonicalize_slot(slot, contract_type)
    # core slots: defer to the hand-written default instructions
    core = {i["name"]: i for i in default_slot_instructions("")}
    if canon in core:
        return dict(core[canon])
    if canon in _CONCEPTS:
        m = _CONCEPTS[canon]
        return {"name": canon, "label": m["label"], "description": m["description"],
                "example": m["example"], "required": m["required"]}
    # role-prefixed concept (party_a_address): instruction from the concept stem
    role, rest = _strip_role(canon)
    if rest and rest in _CONCEPTS:
        m = _CONCEPTS[rest]
        side = _role_to_canonical(role, contract_type)
        label = f"{'甲方' if side == 'party_a' else '乙方'}{m['label']}" if side else m["label"]
        return {"name": canon, "label": label, "description": m["description"],
                "example": m["example"], "required": m["required"]}
    return None


def normalize_body_slots(body: str, contract_type: str | None = None) -> str:
    """Rewrite every ``{{slot}}`` in ``body`` to its canonical form."""
    if not body:
        return body
    return _SLOT_RE.sub(lambda m: "{{" + canonicalize_slot(m.group(1), contract_type) + "}}", body)


def normalize_instruction_names(instructions: list[dict], contract_type: str | None = None) -> list[dict]:
    """Rewrite each instruction's ``name`` to its canonical slot name (keeps labels)."""
    out = []
    for ins in instructions or []:
        canon = canonicalize_slot(ins.get("name", ""), contract_type)
        out.append({**ins, "name": canon})
    return out


# ---------------------------------------------------------------------------
# Chinese render pass (assembly-time)
# ---------------------------------------------------------------------------
# The DB clause corpus carries Latin canonical slots ({{party_a}}, {{amount}},
# {{party_a_address}}, ...). The user wants every *generated* (assembled)
# contract to carry Chinese slot names. Rather than migrate the corpus, we
# render Latin -> Chinese at assembly time: ``render_body_chinese`` rewrites
# the assembled body, ``chinese_instruction_for_slot`` returns instructions
# whose ``name`` matches the rendered Chinese tokens so the coherence gate
# (slot name == instruction name) still passes.
#
# Canonicalization stays Latin (so DB writes + variant/role-prefix logic +
# the existing tests are untouched); the Chinese form is a *display render*
# layered on top.

def _chinese_name(canon: str, contract_type: str | None, l2c: dict[str, str]) -> str:
    """Map a Latin canonical slot to its Chinese display name.

    Precedence: per-type manifest ``latin`` bridge (per-type names like
    借款金额) -> role-prefixed attribute via the concept label (甲方联系地址)
    -> bare concept label (联系地址). Returns ``canon`` unchanged when no
    Chinese mapping is known (unknown single-occurrence slots stay Latin).
    """
    if canon in l2c:
        return l2c[canon]
    # role-prefixed attribute: party_a_address -> 甲方联系地址
    role, rest = _strip_role(canon)
    if rest and rest in _CONCEPTS:
        m = _CONCEPTS[rest]
        side = _role_to_canonical(role, contract_type)
        if side == "party_a":
            return f"甲方{m['label']}"
        if side == "party_b":
            return f"乙方{m['label']}"
        return m["label"]
    # bare concept: address -> 联系地址, legal_rep -> 法定代表人
    if canon in _CONCEPTS:
        return _CONCEPTS[canon]["label"]
    return canon


def render_body_chinese(body: str, contract_type: str | None = None) -> str:
    """Render every ``{{slot}}`` in ``body`` to its Chinese display name.

    Applied at assembly time (after the body is assembled from clause bodies)
    so the final generated contract carries Chinese slot names. Each slot is
    canonicalized first (variant/role-prefix -> Latin concept), then mapped to
    the per-type Chinese name. Slots with no Chinese mapping (unknown
    single-occurrence slots) are left unchanged so their clause-declared
    instructions still match.
    """
    if not body:
        return body
    l2c = latin_to_chinese_map(contract_type) if contract_type else {}
    return _SLOT_RE.sub(
        lambda m: "{{" + _chinese_name(canonicalize_slot(m.group(1), contract_type), contract_type, l2c) + "}}",
        body,
    )


def chinese_instruction_for_slot(slot: str, contract_type: str | None = None) -> dict | None:
    """Return a slot instruction dict with a Chinese ``name``, or None.

    Mirrors :func:`instruction_for_slot` but renders the slot ``name`` to
    Chinese so it matches the Chinese tokens in a :func:`render_body_chinese`
    body. Returns ``None`` when no Chinese mapping exists (the caller should
    keep the original instruction so an unknown slot still matches its
    clause-declared instruction).
    """
    canon = canonicalize_slot(slot, contract_type)
    l2c = latin_to_chinese_map(contract_type) if contract_type else {}
    cn = _chinese_name(canon, contract_type, l2c)
    if cn == canon:
        return None  # no Chinese mapping - caller keeps the original instruction
    base = instruction_for_slot(slot, contract_type)
    if base is not None:
        return {**base, "name": cn}
    # concept not reachable via instruction_for_slot (e.g. bare attribute stem)
    role, rest = _strip_role(canon)
    if rest and rest in _CONCEPTS:
        m = _CONCEPTS[rest]
        side = _role_to_canonical(role, contract_type)
        label = f"{'甲方' if side == 'party_a' else '乙方'}{m['label']}" if side else m["label"]
        return {"name": cn, "label": label, "description": m["description"],
                "example": m["example"], "required": m["required"]}
    if canon in _CONCEPTS:
        m = _CONCEPTS[canon]
        return {"name": cn, "label": m["label"], "description": m["description"],
                "example": m["example"], "required": m["required"]}
    return None


def render_instructions_chinese(
    instructions: list[dict], contract_type: str | None = None
) -> list[dict]:
    """Remap each instruction's ``name`` to its Chinese display name.

    Mirrors :func:`render_body_chinese` so the instruction names match the
    Chinese body slots after the render pass. Instructions whose name has no
    Chinese mapping keep their original (Latin) name so they still match any
    body slot that was likewise left unchanged. Dedupes by the rendered name
    (two Latin concepts may collapse to one Chinese name within a type).
    """
    if not instructions:
        return instructions
    l2c = latin_to_chinese_map(contract_type) if contract_type else {}
    out: list[dict] = []
    seen: set[str] = set()
    for ins in instructions:
        canon = canonicalize_slot(ins.get("name", ""), contract_type)
        cn = _chinese_name(canon, contract_type, l2c)
        if cn in seen:
            continue
        seen.add(cn)
        out.append({**ins, "name": cn})
    return out


__all__ = [
    "canonicalize_slot",
    "instruction_for_slot",
    "normalize_body_slots",
    "normalize_instruction_names",
    "render_body_chinese",
    "render_instructions_chinese",
    "chinese_instruction_for_slot",
]


