#!/usr/bin/env python3
"""Parallel batch tagging with rate limiting and progress tracking.

This script processes ALL contract types in parallel (threaded), respecting
API rate limits per process while maximizing throughput.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

import litellm
from src.clauses.tags import load_vocab_from_db, TAG_VOCAB
from src.eval.rubric import list_rubrics, load_criteria


# Rate limiting state (per-thread-safe)
_lock = threading.Lock()
_request_count = 0
_last_request_time = 0
_MIN_INTERVAL = 2.5  # 24 req/min instead of 20 to be safe


def classify_clause_safe(
    clause_body: str,
    clause_section: str,
    criteria: list,
    model: str = "openai/qwen-3.7-plus",
) -> Optional[str]:
    """Classify clause with rate limiting and retry."""
    global _request_count, _last_request_time

    # Rate limiting
    with _lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_request_time = time.time()
        _request_count += 1

        if _request_count % 50 == 0:
            print(f"  Requests made: {_request_count}", file=sys.stderr)

    try:
        # Build prompt
        criteria_text = "\n".join(
            f"- {c['id']}: {c['title']}"
            for c in criteria[:5]  # Limit context
        )

        prompt = f"""你是法律条款分类助手。请判断以下合同条款主要对应哪个评审标准。

条款所在章节：{clause_section}
条款内容:
{clause_body[:800]}

评审标准列表:
{criteria_text}

只输出评审标准 ID。无法判断时输出 none。"""

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=30,
        )

        result = response.choices[0].message.content.strip()

        # Extract valid criterion id
        valid_ids = {c["id"] for c in criteria}
        for cid in valid_ids:
            if cid in result.lower():
                return cid
        return None

    except Exception as e:
        # Don't fail entire run on single error
        return None


def process_contract_type(
    contract_type: str,
    dry_run: bool = False,
    model: str = "openai/qwen-3.7-plus",
) -> Dict:
    """Process one contract type, returning stats."""
    from src.clauses.store import list_clauses, update_clause

    result = {
        "type": contract_type,
        "tagged": 0,
        "already_tagged": 0,
        "errors": 0,
        "distribution": {},
        "success": False,
        "error": None,
    }

    try:
        # Load rubric
        rubrics = [r for r in list_rubrics() if r["name"].startswith(f"contract_{contract_type}_")]
        if not rubrics:
            result["error"] = "No rubric found"
            return result

        latest_rubric = max(rubrics, key=lambda r: r["name"])
        criteria = load_criteria(latest_rubric["name"])

        # Load clauses
        clauses = list_clauses(contract_type=contract_type)

        print(f"\n{'='*60}")
        print(f"{contract_type}: {len(clauses)} clauses")
        print(f"Rubric: {latest_rubric['name']} ({len(criteria)} topics)")
        print('-'*60)

        for i, clause in enumerate(clauses, 1):
            clause_id = clause["id"]
            section = clause.get("section", "未知")
            body = clause.get("body", "")
            current_tags = clause.get("tags", {})

            # Skip if already has legal_topic
            if "legal_topic" in current_tags:
                result["already_tagged"] += 1
                continue

            # Classify
            legal_topic = classify_clause_safe(body, section, criteria, model)

            if legal_topic:
                result["tagged"] += 1
                result["distribution"][legal_topic] = \
                    result["distribution"].get(legal_topic, 0) + 1

                if not dry_run:
                    new_tags = {**current_tags, "legal_topic": legal_topic}
                    try:
                        update_clause(clause_id, fields={"tags": new_tags})
                    except Exception as e:
                        result["errors"] += 1
            else:
                result["errors"] += 1

            if i % 100 == 0 or i == len(clauses):
                print(f"  [{i}/{len(clauses)}] tagged={result['tagged']} already={result['already_tagged']} errors={result['errors']}")

        result["success"] = True
        print(f"\n✅ {contract_type} complete:")
        print(f"   Tagged: {result['tagged']}, Already: {result['already_tagged']}, Errors: {result['errors']}")
        print(f"   Distribution: {result['distribution']}")

    except Exception as e:
        result["error"] = str(e)
        result["success"] = False
        print(f"❌ {contract_type} failed: {e}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Process all types")
    parser.add_argument("--types", nargs="+", help="Specific types")
    parser.add_argument("--max-workers", type=int, default=4, help="Thread pool size")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="openai/qwen-3.7-plus")
    args = parser.parse_args()

    load_vocab_from_db()

    # Get types to process
    if args.all:
        from src.contracts.templates import list_contract_types
        types = [t["key"] for t in list_contract_types()]
    elif args.types:
        types = args.types
    else:
        parser.error("Either --all or --types is required")

    print(f"Processing {len(types)} types with {args.max_workers} threads...")

    # Process in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(process_contract_type, t, dry_run=args.dry_run, model=args.model): t
            for t in types
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)

    total_tagged = sum(r["tagged"] for r in results if r["success"])
    total_errors = sum(r["errors"] for r in results if r["success"])
    successful = sum(1 for r in results if r["success"])

    print(f"Successful: {successful}/{len(types)}")
    print(f"Total tagged: {total_tagged}")
    print(f"Total errors: {total_errors}")

    # Show coverage gaps
    print(f"\nCoverage status by type:")
    for r in sorted(results, key=lambda x: -x["tagged"])[:10]:
        if r["success"]:
            n_topics = len(set(r["distribution"].keys()))
            print(f"  {r['type']:30} ✓ {n_topics}/{max(5, len(r['distribution']))} topics covered")
        else:
            print(f"  {r['type']:30} ✗ ERROR: {r['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
