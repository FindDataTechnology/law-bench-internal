#!/usr/bin/env python3
"""Batch-tag existing clauses with legal_topic based on rubric criteria.

Uses LLM to classify each clause body against rubric criterion guidance,
assigning the most relevant legal_topic. This establishes the semantic bridge
between clauses and rubric criteria for the V4 self-iteration pipeline.

Usage:
    # Tag all sale clauses
    python scripts/backfill_legal_topics.py --contract-type sale

    # Tag all types
    python scripts/backfill_legal_topics.py --all

    # Dry run (show what would be tagged)
    python scripts/backfill_legal_topics.py --contract-type sale --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

# Suppress litellm cost map warnings
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

import litellm

from src.clauses.tags import load_vocab_from_db, TAG_VOCAB
from src.eval.rubric import load_criteria


def classify_clause_legal_topic(
    clause_body: str,
    clause_section: str,
    criteria: list[dict],
    model: str = "glm-5",
    max_retries: int = 5,
) -> Optional[str]:
    """Use LLM to classify which rubric criterion a clause primarily addresses.

    Args:
        clause_body: The clause body text
        clause_section: The section heading (e.g., "权利义务", "违约责任")
        criteria: List of rubric criteria with id, title, guidance
        model: LLM model to use for classification
        max_retries: Max retry attempts on rate-limit errors

    Returns:
        The criterion id (legal_topic) or None if classification fails
    """
    # Build prompt with criteria guidance
    criteria_text = "\n".join(
        f"- {c['id']}: {c['title']}\n  Guidance: {c.get('match_criteria', c.get('guidance', ''))[:200]}"
        for c in criteria
    )

    prompt = f"""你是法律条款分类助手。请判断以下合同条款主要对应哪个评审标准。

条款所在章节: {clause_section}
条款内容:
{clause_body[:1000]}

评审标准列表:
{criteria_text}

请输出该条款最主要对应的评审标准ID（只输出ID，不要其他内容）。如果无法判断，输出"none"。"""

    for attempt in range(max_retries):
        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=50,
            )
            result = response.choices[0].message.content.strip()

            # Validate result is a valid criterion id
            valid_ids = {c["id"] for c in criteria}
            if result in valid_ids:
                return result
            elif result.lower() == "none":
                return None
            else:
                # Try to extract a valid id from the response
                for cid in valid_ids:
                    if cid in result:
                        return cid
                return None
        except Exception as e:
            err_str = str(e)
            # Retry on rate-limit, service-unavailable, or connection errors
            if ("RateLimitError" in type(e).__name__ or "RateLimit" in err_str or
                "ServiceUnavailable" in err_str or "InternalServerError" in err_str or
                "Connection error" in err_str):
                wait = 15 * (attempt + 1)  # 15, 30, 45, 60, 75 seconds
                print(f"\n    ⚠ API error (attempt {attempt+1}/{max_retries}), waiting {wait}s...", end=" ")
                time.sleep(wait)
                continue
            print(f"  ⚠ Classification error: {e}")
            return None
    print(f"  ⚠ Max retries ({max_retries}) exhausted")
    return None


def backfill_contract_type(
    contract_type: str,
    dry_run: bool = False,
    model: str = "glm-5",
) -> dict:
    """Backfill legal_topic for all clauses of a contract type.

    Args:
        contract_type: The contract type key
        dry_run: If True, show what would be tagged but don't update
        model: LLM model to use

    Returns:
        Stats dict with counts of tagged/untagged clauses
    """
    from src.clauses.store import list_clauses, update_clause

    print(f"\n{'='*60}")
    print(f"Processing: {contract_type}")
    print(f"{'='*60}")

    # Load rubric criteria
    try:
        # Find latest rubric for this type
        from src.eval.rubric import list_rubrics
        rubrics = [r for r in list_rubrics() if r["name"].startswith(f"contract_{contract_type}_")]
        if not rubrics:
            print(f"⚠ No rubric found for {contract_type}")
            return {"tagged": 0, "untagged": 0, "errors": 0}

        latest_rubric = max(rubrics, key=lambda r: r["name"])
        criteria = load_criteria(latest_rubric["name"])
        print(f"Rubric: {latest_rubric['name']} ({len(criteria)} criteria)")
    except Exception as e:
        print(f"⚠ Error loading rubric: {e}")
        return {"tagged": 0, "untagged": 0, "errors": 0}

    # Load clauses
    try:
        clauses = list_clauses(contract_type=contract_type)
        print(f"Clauses: {len(clauses)}")
    except Exception as e:
        print(f"⚠ Error loading clauses: {e}")
        return {"tagged": 0, "untagged": 0, "errors": 0}

    # Classify each clause
    tagged_count = 0
    untagged_count = 0
    error_count = 0
    topic_distribution = {}

    for i, clause in enumerate(clauses, 1):
        clause_id = clause["id"]
        section = clause.get("section", "未知")
        body = clause.get("body", "")
        current_tags = clause.get("tags", {})

        # Skip if already has legal_topic
        if "legal_topic" in current_tags:
            print(f"  [{i}/{len(clauses)}] id={clause_id} section={section} → already tagged: {current_tags['legal_topic']}")
            topic_distribution[current_tags["legal_topic"]] = topic_distribution.get(current_tags["legal_topic"], 0) + 1
            tagged_count += 1
            continue

        # Rate limiting: 2 seconds between requests to stay under relay limits
        if i > 1:
            time.sleep(2)

        # Classify
        print(f"  [{i}/{len(clauses)}] id={clause_id} section={section} → classifying...", end=" ")
        legal_topic = classify_clause_legal_topic(body, section, criteria, model=model)

        if legal_topic:
            print(f"✓ {legal_topic}")
            topic_distribution[legal_topic] = topic_distribution.get(legal_topic, 0) + 1

            if not dry_run:
                # Update clause tags
                new_tags = {**current_tags, "legal_topic": legal_topic}
                try:
                    update_clause(clause_id, fields={"tags": new_tags})
                    tagged_count += 1
                except Exception as e:
                    print(f"    ⚠ Update error: {e}")
                    error_count += 1
            else:
                tagged_count += 1
        else:
            print("✗ (no match)")
            untagged_count += 1

    # Print summary
    print(f"\n{'─'*60}")
    print(f"Summary for {contract_type}:")
    print(f"  Tagged: {tagged_count}")
    print(f"  Untagged: {untagged_count}")
    print(f"  Errors: {error_count}")
    print(f"  Topic distribution:")
    for topic, count in sorted(topic_distribution.items(), key=lambda x: -x[1]):
        print(f"    {topic}: {count}")

    return {
        "tagged": tagged_count,
        "untagged": untagged_count,
        "errors": error_count,
        "distribution": topic_distribution,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-type", help="Contract type to process")
    parser.add_argument("--all", action="store_true", help="Process all contract types")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tagged")
    parser.add_argument("--model", default="glm-5", help="LLM model for classification")
    args = parser.parse_args()

    if not args.contract_type and not args.all:
        parser.error("Either --contract-type or --all is required")

    # Load vocab from DB
    load_vocab_from_db()

    if args.all:
        # Get all contract types
        from src.contracts.templates import list_contract_types
        types = [t["key"] for t in list_contract_types()]
        print(f"Processing {len(types)} contract types...")

        total_stats = {"tagged": 0, "untagged": 0, "errors": 0}
        for contract_type in types:
            stats = backfill_contract_type(contract_type, dry_run=args.dry_run, model=args.model)
            for key in ["tagged", "untagged", "errors"]:
                total_stats[key] += stats.get(key, 0)

        print(f"\n{'='*60}")
        print(f"TOTAL: {total_stats}")
        print(f"{'='*60}")
    else:
        backfill_contract_type(args.contract_type, dry_run=args.dry_run, model=args.model)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
