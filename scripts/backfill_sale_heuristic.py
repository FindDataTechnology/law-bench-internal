#!/usr/bin/env python3
"""Heuristic backfill for V4 pilot - no LLM, just keyword matching."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.store import list_clauses, update_clause


# Map clause keywords/topics to rubric criteria IDs
RULES = [
    # party_identification: mentions specific party info
    ("party_identification", ["统一社会信用代码", "法定代表人", "联系人"]),
    # governing_law_present: dispute resolution language
    ("governing_law_present", ["管辖", "courts", "仲裁", "dispute resolution"]),
    # ownership_transfer: delivery/transfer terms
    ("ownership_transfer", ["交付", "delivery", "移交", "所有权转移"]),
    # risk_transfer_point: risk language
    ("risk_transfer_point", ["风险", "risk of loss", "损失承担"]),
    # inspection_period: quality acceptance terms
    ("inspection_period", ["检验", "验收", "inspection", "acceptance", "期限"]),
    # defect_warranty: warranty/guarantee language
    ("defect_warranty", ["质量担保", "warranty", "guarantee", "瑕疵"]),
    # ownership_retention: title retention specifically
    ("ownership_retention", ["所有权保留", "retain title", "title retention"]),
    # legal_citation_accuracy: legal basis/civil code citations
    ("legal_citation_accuracy", ["《民法典", "Civil Code", "法律依据", "法律规定"]),
    # clause_completeness: general completeness/intro language
    ("clause_completeness", ["鉴于", "purpose", "background", "合同目的"]),
    # payment terms (optional secondary)
    ("payment_terms", ["价款", "支付", "price", "payment"]),
]


def classify_heuristic(body: str, section: str) -> str | None:
    """Classify using simple keyword matching."""
    text = (body + " " + section).lower()

    for topic, keywords in RULES:
        for kw in keywords:
            if kw.lower() in text:
                return topic

    return None


def run_fast_backfill():
    """Tag all sale clauses quickly using heuristics."""
    print("\n=== Fast Heuristic Backfill ===")

    clauses = list_clauses(contract_type="sale")
    print(f"Processing {len(clauses)} clauses...")

    tagged_count = 0
    distribution = {}

    for i, c in enumerate(clauses, 1):
        body = c.get("body", "")
        section = c.get("section", "")
        tags = c.get("tags", {})

        if "legal_topic" in tags:
            continue

        topic = classify_heuristic(body, section)
        if topic:
            new_tags = {**tags, "legal_topic": topic}
            try:
                update_clause(c["id"], fields={"tags": new_tags})
                tagged_count += 1
                distribution[topic] = distribution.get(topic, 0) + 1

                if i % 200 == 0:
                    print(f"  [{i}/{len(clauses)}] Tagged: {tagged_count}")
            except Exception as e:
                print(f"  Update error at {i}: {e}")

    print(f"\n=== Summary ===")
    print(f"Tagged: {tagged_count}")
    print(f"Distribution:")
    for t, cnt in sorted(distribution.items(), key=lambda x: -x[1]):
        print(f"  {t}: {cnt}")


if __name__ == "__main__":
    run_fast_backfill()
