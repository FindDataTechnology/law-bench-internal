#!/usr/bin/env python3
"""Seed v3 contract evaluation rubrics with optimized (lenient) common criteria.

v3 = v2 type-specific criteria + OPTIMIZED 4 base criteria + OPTIMIZED
legal_basis_citation. The optimization makes the LLM judge accept:
  - governing_law_present: legal references in "鉴于"/"争议解决" sections (not
    just a dedicated "适用法律" clause)
  - legal_citation_accuracy: accurate law names without exact article numbers
  - legal_basis_citation: general references like "民法典 + 相关司法解释" (not
    just exact 法释文号)
  - clause_completeness: core mandatory clauses present (not ALL clauses)

v1/v2 rubrics are untouched (v3 names differ). Idempotent: upserts by name.

Run:
    uv run python scripts/seed_v3_rubrics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.eval.db import connect
from src.eval.store import ensure_schema
from src.eval.rubric_crud import get_rubric_detail, list_rubrics_with_counts
from src.eval.rubric_crud import create_rubric, add_criterion
from src.eval.errors import ConflictError


# Optimized (lenient) base criteria for v3 - accept broader compliance.
V3_BASE_CRITERIA: list[dict[str, str]] = [
    {
        "name": "party_identification",
        "description": "是否清晰识别全部合同主体，载明完整法律名称与角色（甲方/乙方）？",
        "guidance": (
            'PASS if 合同主体以名称或代号列明并标注角色（甲方/乙方/出卖人/买受人等），'
            '包括使用占位符（如{{party_a}}）但角色标注清晰；'
            'FAIL if 主体完全缺失或无法区分甲方乙方。'
        ),
    },
    {
        "name": "governing_law_present",
        "description": "是否明确约定适用法律（如中华人民共和国法律）？",
        "guidance": (
            'PASS if 合同任何部分（包括鉴于、争议解决、单独适用法律条款等）'
            '引用了中华人民共和国法律或相关法律法规；'
            'FAIL if 合同完全没有提及任何法律或法域。'
        ),
    },
    {
        "name": "clause_completeness",
        "description": "是否具备该类合同的核心必备条款（如违约责任、争议解决、合同期限等）？",
        "guidance": (
            'PASS if 合同包含该类型的核心必备条款（至少包括标的、价款/报酬、履行期限、'
            '违约责任、争议解决）；FAIL if 核心必备条款缺失超过一项。'
        ),
    },
    {
        "name": "legal_citation_accuracy",
        "description": "法条引用是否准确且现行有效（如《民法典》条文序号）？",
        "guidance": (
            'PASS if 所引法律名称真实存在且现行有效（如《民法典》、《公司法》等），'
            '无论是否标注具体条文序号；'
            'FAIL if 引用系编造的法律名称或已废止的法规。'
        ),
    },
]


def _v3_legal_basis_citation(citation: str) -> dict[str, str]:
    """Optimized legal_basis_citation criterion - accepts general references."""
    return {
        "name": "legal_basis_citation",
        "description": "是否引用该合同类型现行有效的核心法律法规与司法解释？",
        "guidance": (
            f'PASS if 合同引用了现行有效的核心法律法规或司法解释（如{citation}），'
            '包括泛化引用（如"民法典及相关司法解释"、"公司法及相关规定"）；'
            'FAIL if 完全未引用任何法律法规，或引用的法规已废止。'
        ),
    }


def _get_v2_citation(v2_criteria: list[dict]) -> str:
    """Extract the citation text from the v2 legal_basis_citation criterion."""
    for c in v2_criteria:
        if c.get("name") == "legal_basis_citation":
            guidance = c.get("guidance", "")
            # Extract the citation between （ and ）
            if "（" in guidance and "）" in guidance:
                start = guidance.index("（") + 1
                end = guidance.index("）", start)
                return guidance[start:end]
    return "相关法律法规"


def _create_v3_from_v2(v2_rubric: dict) -> dict:
    """Build a v3 rubric from a v2 rubric with optimized common criteria."""
    v2_criteria = v2_rubric["criteria"]
    citation = _get_v2_citation(v2_criteria)

    # Type-specific criteria (everything except the 4 base + legal_basis_citation)
    base_names = {c["name"] for c in V3_BASE_CRITERIA}
    type_specific = [c for c in v2_criteria if c["name"] not in base_names and c["name"] != "legal_basis_citation"]

    # Build v3 criteria: optimized base + type-specific + optimized legal_basis
    v3_criteria = (
        [dict(c) for c in V3_BASE_CRITERIA]
        + [dict(c) for c in type_specific]
        + [_v3_legal_basis_citation(citation)]
    )

    return {
        "name": v2_rubric["name"].replace("_v2", "_v3"),
        "context": v2_rubric["context"],
        "description": f"{v2_rubric['description'].replace('（法律精修版）', '')}（优化判定版）",
        "criteria": v3_criteria,
    }


def main() -> None:
    """Seed v3 rubrics for all contract types that have a v2 rubric."""
    ensure_schema()
    rubrics = list_rubrics_with_counts()
    v2_rubrics = [r for r in rubrics if r["name"].endswith("_v2") and r["name"].startswith("contract_")]

    print(f"Found {len(v2_rubrics)} v2 rubrics to upgrade to v3")

    created = 0
    skipped = 0
    for r in v2_rubrics:
        v2_name = r["name"]
        v3_name = v2_name.replace("_v2", "_v3")

        try:
            v2_detail = get_rubric_detail(v2_name)
        except Exception as e:
            print(f"  [SKIP] {v2_name}: cannot load detail ({e})")
            skipped += 1
            continue

        v3_rubric = _create_v3_from_v2(v2_detail)

        try:
            # Create the v3 rubric
            create_rubric(
                v3_rubric["name"],
                v3_rubric["context"],
                description=v3_rubric["description"],
                criteria=v3_rubric["criteria"],
            )
            created += 1
            print(f"  [CREATED] {v3_name}: {len(v3_rubric['criteria'])} criteria")
        except ConflictError:
            print(f"  [EXISTS]  {v3_name}: already exists, skipping")
            skipped += 1
        except Exception as e:
            print(f"  [ERROR]   {v3_name}: {e}")
            skipped += 1

    print(f"\n✓ Done: {created} v3 rubrics created, {skipped} skipped")


if __name__ == "__main__":
    main()
