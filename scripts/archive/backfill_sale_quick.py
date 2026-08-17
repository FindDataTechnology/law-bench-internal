#!/usr/bin/env python3
"""Quick backfill for sale - target only key clauses needed for V4 pilot.

This is a streamlined version that tags only the most critical clauses needed
to demonstrate the V4 pipeline capability, rather than all 1305 clauses.

Strategy: Tag one representative clause per rubric criterion per section.
This gives us quick coverage (~100 clauses) to prove the concept while
the full backfill runs in background.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from src.clauses.tags import TAG_VOCAB
from src.eval.rubric import list_rubrics, load_criteria


def find_clause_match_topic(clause_body: str, clause_section: str, criteria: list) -> str | None:
    """Heuristic matching based on keywords and section names."""

    topic_mappings = {
        "party_identification": ["当事人", "甲方", "乙方", "Party", "name", "名称", "统一社会信用代码"],
        "governing_law_present": ["争议解决", "管辖", "适用法律", "governing law", "法律适用", "court jurisdiction"],
        "clause_completeness": ["鉴于", "Contract Purpose", "purpose", "背景", "目的"],
        "legal_citation_accuracy": ["违约责任", "违约", "Breach", "liability", "赔偿", "penalty", "违约金"],
        "ownership_transfer": ["交付", "delivery", "transfer", "所有权转移", "transfer ownership", "移交"],
        "risk_transfer_point": ["风险", "risk", "风险转移", "loss", "damage", "risk of loss"],
        "inspection_period": ["检验", "验收", "inspection", "验收期限", "检验期限", "quality check", "acceptance"],
        "defect_warranty": ["质量", "quality", "warranty", "guarantee", "defect", "缺陷", "瑕疵担保"],
        "ownership_retention": ["所有权保留", "ownership retention", "retain title", "保留所有权", "title retention"],
        "clause_completeness": ["主要条款", "essential", "key terms", "核心条款"],
    }

    text_lower = (clause_body + " " + clause_section).lower()

    # Prioritize by specificity - match most specific keywords first
    prioritized_order = [
        ("ownership_retention", ["所有权保留", "retain title"]),
        ("inspection_period", ["验收期限", "检验期限"]),
        ("risk_transfer_point", ["风险转移", "risk of loss"]),
        ("defect_warranty", ["瑕疵担保", "quality warranty"]),
        ("ownership_transfer", ["所有权转移"]),
        ("governing_law_present", ["法律适用", "governing law", "管辖法院"]),
        ("legal_citation_accuracy", ["法律依据", "Civil Code"]),
        ("party_identification", ["统一社会信用代码", "party identification"]),
    ]

    for topic, keywords in prioritized_order:
        for kw in keywords:
            if kw.lower() in text_lower:
                return topic

    # Then try general mappings
    for topic, keywords in topic_mappings.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return topic

    return None


def quick_backfillSale(dry_run=False):
    """Quick backfill targeting ~100 key clauses."""
    from src.clauses.store import list_clauses, update_clause

    print(f"\n{'='*60}")
    print(f"Quick Backfill: Sale Contract")
    print(f"{'='*60}")

    # Load rubric criteria
    rubrics = [r for r in list_rubrics() if r["name"].startswith("contract_sale_")]
    latest_rubric = max(rubrics, key=lambda r: r["name"])
    criteria = load_criteria(latest_rubric["name"])
    print(f"Rubric: {latest_rubric['name']} ({len(criteria)} criteria)")

    # Load clauses
    clauses = list_clauses(contract_type="sale")
    print(f"Clauses: {len(clauses)}")

    # Group by section
    sections = {}
    for c in clauses:
        sec = c.get("section", "other")
        if sec not in sections:
            sections[sec] = []
        sections[sec].append(c)

    # Track what we've tagged
    tagged_count = 0
    topic_distribution = {}

    # Strategy: For each rubric topic, find a clause that matches via heuristic
    for i, clause in enumerate(clauses[:200], 1):  # Process first 200 (covers most sections)
        clause_id = clause["id"]
        section = clause.get("section", "未知")
        body = clause.get("body", "")
        current_tags = clause.get("tags", {})

        # Skip if already has legal_topic
        if "legal_topic" in current_tags:
            continue

        # Heuristic classification
        legal_topic = find_clause_match_topic(body, section, criteria)

        if legal_topic:
            new_tags = {**current_tags, "legal_topic": legal_topic}

            if not dry_run:
                try:
                    update_clause(clause_id, fields={"tags": new_tags})
                    tagged_count += 1
                    topic_distribution[legal_topic] = topic_distribution.get(legal_topic, 0) + 1
                    print(f"[{i}] id={clause_id} section={section} → {legal_topic} ✓")
                except Exception as e:
                    print(f"[{i}] id={clause_id} update error: {e}")
            else:
                tagged_count += 1
                topic_distribution[legal_topic] = topic_distribution.get(legal_topic, 0) + 1
                print(f"[{i}] id={clause_id} section={section} → {legal_topic} (dry-run)")
        else:
            if i % 50 == 0:
                print(f"[{i}] No match for section={section}")

    # Print summary
    print(f"\n{'─'*60}")
    print(f"Quick Backfill Summary:")
    print(f"  Tagged: {tagged_count}")
    print(f"  Topic distribution:")
    for topic, count in sorted(topic_distribution.items(), key=lambda x: -x[1]):
        print(f"    {topic}: {count}")

    return {"tagged": tagged_count, "distribution": topic_distribution}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    quick_backfillSale(dry_run=args.dry_run)
