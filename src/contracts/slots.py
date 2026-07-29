"""Slot-instruction model for contract templates.

A *slot instruction* documents a single ``{{slot}}`` placeholder: what it is,
how to fill it, an example, and whether it is required. Instructions are
generated alongside the templates into ``src/contracts/data/contracts.json``
and live in this contracts layer (they are not a change to ``document-generation``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.eval.errors import NotFoundError

from .templates import _registry, get_template


@dataclass
class SlotInstruction:
    """Structured guidance for one ``{{slot}}`` placeholder."""

    name: str
    label: str
    description: str
    example: str
    required: bool

    def to_dict(self) -> dict:
        return asdict(self)


def get_slot_instructions(contract_type: str) -> list[dict]:
    """Return the slot-instruction manifest for ``contract_type``.

    A list of ``{name, label, description, example, required}``. Raises
    :class:`NotFoundError` for an unknown type.
    """
    entry = _registry().get(contract_type)
    if entry is None:
        raise NotFoundError(f"unknown contract type: {contract_type!r}")
    return [dict(si) for si in entry.get("slot_instructions", [])]


def check_slot_consistency(contract_type: str) -> tuple[list[str], list[str]]:
    """Return ``(missing_instructions, extra_instructions)`` for ``contract_type``.

    ``missing_instructions`` lists template slots without an instruction;
    ``extra_instructions`` lists instructions for slots absent from the template.
    A consistent template has both lists empty.
    """
    template_slots = set(get_template(contract_type)["slots"])
    instr_names = {si["name"] for si in get_slot_instructions(contract_type)}
    missing = sorted(template_slots - instr_names)
    extra = sorted(instr_names - template_slots)
    return missing, extra


# The canonical slot set + default instruction manifest for contract templates.
# Single source of truth shared by scripts/seed_contract_templates.py (skeleton)
# and scripts/generate_contract_templates_llm.py (type-specific) so they stay in
# sync. The 12 names MUST match the {{slot}} tokens used in the template bodies.
REQUIRED_SLOTS = (
    "party_a", "party_b", "subject", "amount", "term_start", "term_end",
    "party_a_duty", "party_b_duty", "penalty", "jurisdiction",
    "sign_date", "sign_location",
)


def default_slot_instructions(zh: str) -> list[dict]:
    """The default slot-instruction manifest for a contract of type ``zh``.

    The ``subject`` example is tailored to the contract type; the rest are shared.
    """
    subject_example = f"{zh}的具体标的与内容"
    return [
        {"name": "party_a", "label": "甲方名称", "description": "合同甲方（通常为标的提供方/服务方）的全称或姓名", "example": "北京甲科技有限公司", "required": True},
        {"name": "party_b", "label": "乙方名称", "description": "合同乙方的全称或姓名", "example": "北京乙贸易有限公司", "required": True},
        {"name": "subject", "label": "合同标的", "description": "本合同的具体标的、事宜或范围描述", "example": subject_example, "required": True},
        {"name": "amount", "label": "价款金额", "description": "合同价款或费用金额（数字）", "example": "100000", "required": True},
        {"name": "term_start", "label": "履行起始日期", "description": "合同履行开始日期", "example": "2026-01-01", "required": True},
        {"name": "term_end", "label": "履行结束日期", "description": "合同履行结束日期", "example": "2026-12-31", "required": True},
        {"name": "party_a_duty", "label": "甲方义务", "description": "甲方在本合同项下的主要义务", "example": "按期交付标的物并转移所有权", "required": True},
        {"name": "party_b_duty", "label": "乙方义务", "description": "乙方在本合同项下的主要义务", "example": "按期足额支付价款", "required": True},
        {"name": "penalty", "label": "违约金", "description": "违约金数额或计算方式", "example": "合同价款的10%", "required": False},
        {"name": "jurisdiction", "label": "争议解决方式", "description": "争议解决方式及管辖/仲裁机构", "example": "提交原告所在地人民法院诉讼解决", "required": False},
        {"name": "sign_date", "label": "签署日期", "description": "合同签署日期", "example": "2026-01-01", "required": True},
        {"name": "sign_location", "label": "签署地点", "description": "合同签署地点", "example": "北京市朝阳区", "required": False},
    ]
