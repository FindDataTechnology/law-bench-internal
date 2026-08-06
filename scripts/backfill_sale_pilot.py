#!/usr/bin/env python3
"""Strategic backfill for sale V4 pilot - tag ONE key clause per needed topic.

Instead of tagging all 1305 clauses, we strategically select representative
clauses for each rubric criterion and use LLM to classify them accurately.

This gives us fast (~2 min) coverage to demonstrate V4 pipeline capability.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

import litellm
from src.clauses.tags import TAG_VOCAB
from src.eval.rubric import list_rubrics, load_criteria


def classify_clause_smart(clause_body: str, clause_section: str, criteria: list) -> str | None:
    """Use LLM classifier but with optimized prompt."""

    # Build concise criteria descriptions
    criteria_text = "\n".join(
        f"- {c['id']}: {c.get('title', c['id'])}\n  {c.get('match_criteria', c.get('guidance', '')[:150])}"
        for c in criteria
    )

    prompt = f"""You are a legal clause classifier. Classify this contract clause into ONE category from the list below.

Rubric Criteria:
{criteria_text}

Clause:
Section: {clause_section}
Content: {clause_body[:800]}

Output ONLY the category ID (e.g., "party_identification") or "none" if unknown."""

    try:
        response = litellm.completion(
            model="glm-5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=20,
        )
        result = response.choices[0].message.content.strip()
        valid_ids = {c["id"] for c in criteria}
        if result in valid_ids:
            return result
        for cid in valid_ids:
            if cid in result:
                return cid
        return None
    except Exception as e:
        print(f"  Classification error: {e}")
        return None


def strategic_backfill(dry_run=False):
    """Strategically tag ~15-20 key clauses for rapid V4 demonstration."""
    from src.clauses.store import list_clauses, update_clause

    print(f"\n{'='*60}")
    print(f"Strategic Backfill: Sale V4 Pilot")
    print(f"{'='*60}")

    # Load rubric
    rubrics = [r for r in list_rubrics() if r["name"].startswith("contract_sale_")]
    latest_rubric = max(rubrics, key=lambda r: r["name"])
    criteria = load_criteria(latest_rubric["name"])
    target_topics = [c["id"] for c in criteria]
    print(f"Target topics ({len(target_topics)}): {target_topics}")

    # Load clauses grouped by section
    clauses = list_clauses(contract_type="sale")
    sections = {}
    for c in clauses:
        sec = c.get("section", "other")
        if sec not in sections:
            sections[sec] = []
        sections[sec].append(c)

    print(f"Sections: {list(sections.keys())}")

    # Strategy: For each target topic, find clauses in relevant sections and classify
    tagged_count = 0
    topics_covered = set()
    topic_distribution = {}

    i = 0
    for topic in target_topics:
        if topic in topics_covered:
            continue

        # Find likely section for this topic
        topic_sections = {
            "party_identification": ["当事人"],
            "governing_law_present": ["争议解决"],
            "clause_completeness": ["鉴于", "合同标的"],
            "legal_citation_accuracy": ["违约责任"],
            "ownership_transfer": ["履行期限", "合同履行"],
            "risk_transfer_point": ["履行期限"],
            "inspection_period": ["检验期间"],
            "defect_warranty": ["质量标准", "质量条款", "质量要求"],
            "ownership_retention": ["所有权保留"],
            "clause_completeness": ["价款及支付"],
        }

        likely_sections = topic_sections.get(topic, list(sections.keys()))

        for section in likely_sections:
            if section not in sections:
                continue

            # Sample first few clauses from this section
            for clause in sections[section][:5]:
                i += 1
                clause_id = clause["id"]
                body = clause.get("body", "")

                # Skip already tagged
                current_tags = clause.get("tags", {})
                if current_tags.get("legal_topic") == topic:
                    topics_covered.add(topic)
                    tagged_count += 1
                    topic_distribution[topic] = topic_distribution.get(topic, 0) + 1
                    print(f"[{i}] id={clause_id} section={section} → {topic} (already done)")
                    break

                if current_tags.get("legal_topic"):
                    continue

                print(f"[{i}] Testing {section} clause for {topic}...", end=" ")
                classified = classify_clause_smart(body, section, criteria)

                if classified == topic:
                    new_tags = {**current_tags, "legal_topic": topic}
                    if not dry_run:
                        try:
                            update_clause(clause_id, fields={"tags": new_tags})
                        except Exception as e:
                            print(f"Update failed: {e}")
                            continue

                    topics_covered.add(topic)
                    tagged_count += 1
                    topic_distribution[topic] = topic_distribution.get(topic, 0) + 1
                    print(f"✓ {topic}")
                    break
            else:
                continue
            break  # Found topic, move to next

        if topic not in topics_covered:
            print(f"[{i}] ✗ Could not find clause for {topic}")

    # Summary
    print(f"\n{'─'*60}")
    print(f"Strategic Backfill Summary:")
    print(f"  Tagged: {tagged_count}")
    print(f"  Topics covered: {sorted(topics_covered)}")
    print(f"  Missing: {[t for t in target_topics if t not in topics_covered]}")

    return {"tagged": tagged_count, "covered": sorted(topics_covered)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    strategic_backfill(dry_run=args.dry_run)
