#!/usr/bin/env python3
"""Batch run LangGraph pipeline for all contract types in parallel.

Usage:
    python run_batch_pipeline.py

Requirements:
    - Run from law-template repo root
    - fd-coding-law-bench-mcp source must be accessible
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Add paths
FDC_LAW_BENCH_DIR = Path(__file__).parent / "fd-coding-law-bench-mcp" / "src"
LAW_BENCH_SRC = Path(__file__).parent / "src"

for p in [FDC_LAW_BENCH_DIR, LAW_BENCH_SRC]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def log(msg: str):
    """Print with flush."""
    print(msg, flush=True)


def list_contract_types() -> list[dict]:
    """Get all supported contract types."""
    # Try multiple possible locations
    locations = [
        Path(__file__).parent / "src" / "contracts" / "data" / ".." / "eval" / "seed" / "law_info" / "contract_types.json",
        Path(__file__).parent / "output" / "law_info" / "contract_types.json",
        Path(__file__).parent / "src" / "eval" / "seed" / "law_info" / "contract_types.json",
    ]

    for loc in locations:
        if loc.exists():
            with open(loc, "r", encoding="utf-8") as f:
                return json.load(f)

    raise FileNotFoundError("Could not find contract_types.json")


async def run_single_pipeline(
    contract_type: str,
    stance: str,
    scenario: str,
    max_iterations: int,
    temperature: float,
    semaphore: asyncio.Semaphore | None = None,
) -> dict[str, Any]:
    """Run pipeline for a single contract type."""

    async def _execute():
        # Import inside function to handle warnings properly
        from fd_coding_law_bench_mcp.pipeline.graph import run_pipeline

        tags = {"stance": stance, "scenario": scenario}
        task_desc = f"Draft a balanced {contract_type} contract with generic scenario '{scenario}' (立场均衡，场景：{scenario})"

        log(f"  Starting {contract_type}...")
        start_time = time.time()

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_pipeline(
                contract_type=contract_type,
                tags=tags,
                stance=stance,
                rubric=None,  # Use default rubric for this contract type
                task_desc=task_desc,
                fill_mode="llm",
                temperature=temperature,
                max_iterations=max_iterations,
                custom_clause_ids=None,
            ),
        )

        elapsed = time.time() - start_time
        log(f"  ✓ {contract_type} completed in {elapsed:.1f}s")
        return result

    if semaphore:
        async with semaphore:
            return await _execute()
    else:
        return await _execute()


async def main():
    """Main entry point: run all pipelines in parallel with concurrency limit."""
    log("=" * 80)
    log("Batch Pipeline Runner - All Contract Types")
    log("=" * 80)

    # Get all contract types
    log("\nLoading contract types...")
    contract_types_list = list_contract_types()
    contract_types = [ct["key"] for ct in contract_types_list]

    log(f"\nFound {len(contract_types)} contract types:")
    for i, ct in enumerate(contract_types):
        zh_name = next((ct.get("zh", "") for ct in contract_types_list if ct["key"] == ct), "?")
        log(f"  {i+1:2d}. {ct:30s} ({zh_name})")

    # Concurrency limit: 3 at a time
    CONCURRENT_LIMIT = 3
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)

    # Create tasks
    tasks = [
        run_single_pipeline(
            contract_type=ct,
            stance="balanced",
            scenario="一般",
            max_iterations=2,
            temperature=0.0,
            semaphore=semaphore,
        )
        for ct in contract_types
    ]

    log(f"\nStarting batch pipeline execution (concurrency={CONCURRENT_LIMIT})...")
    start_time = time.time()

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.time()
    elapsed = end_time - start_time

    # Process results
    output_dir = Path(__file__).parent / "output" / "batch_pipeline_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    final_results = {}
    success_count = 0
    failure_count = 0

    log("\n" + "=" * 80)
    log("RESULTS SUMMARY")
    log("=" * 80)

    for i, (contract_type, result) in enumerate(zip(contract_types, results)):
        if isinstance(result, Exception):
            log(f"[FAIL] {contract_type:30s} {type(result).__name__}: {result}")
            final_results[contract_type] = {
                "status": "error",
                "error": f"{type(result).__name__}: {str(result)}",
            }
            failure_count += 1
        else:
            # Extract relevant fields from result state
            eval_result = result.get("eval_result", {})
            best = result.get("best", {})

            fill_values = result.get("fill_values") or best.get("fill_values", {})
            filled_text_raw = result.get("filled_text") or best.get("filled_text", "")
            filled_text_preview = filled_text_raw[:200] + "... (truncated)" if filled_text_raw else ""

            final_results[contract_type] = {
                "pipeline_run_id": result.get("pipeline_run_id"),
                "eval_run_id": result.get("eval_run_id") or best.get("eval_run_id"),
                "score": eval_result.get("score") or best.get("score"),
                "n_passed": eval_result.get("n_passed") or best.get("n_passed"),
                "n_criteria": eval_result.get("n_criteria"),
                "all_pass": bool(eval_result.get("all_pass")) or best.get("all_pass"),
                "iteration": best.get("iteration") or result.get("iteration", 1),
                "subject": result.get("subject"),
                "party_a": result.get("party_a"),
                "party_b": result.get("party_b"),
                "fill_values": fill_values,
                "filled_text_preview": filled_text_preview,
                "status": "success",
            }
            success_count += 1
            status_str = "ALL PASS ✓" if final_results[contract_type]["all_pass"] else f"passed={final_results[contract_type]['n_passed']}/{final_results[contract_type]['n_criteria']}"
            # Handle potentially None/missing score gracefully
            score_val = final_results[contract_type].get('score')
            score_str = f"{score_val:.1f}" if isinstance(score_val, (int, float)) else str(score_val) if score_val is not None else "N/A"
            log(f"[OK]   {contract_type:30s} score={score_str:>6} {status_str} iter={final_results[contract_type]['iteration']}")

    # Write full results to JSON file
    results_file = output_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": len(contract_types),
                "success": success_count,
                "failure": failure_count,
                "elapsed_seconds": round(elapsed, 2),
                "elapsed_minutes": round(elapsed / 60, 2),
                "concurrency_limit": CONCURRENT_LIMIT,
                "parameters": {
                    "stance": "balanced",
                    "scenario": "一般",
                    "max_iterations": 2,
                    "temperature": 0.0,
                },
            },
            "results": final_results,
        }, ensure_ascii=False, indent=2)

    log("\n" + "=" * 80)
    log("BATCH PIPELINE COMPLETE")
    log("=" * 80)
    log(f"Total contracts processed: {len(contract_types)}")
    log(f"Successfully completed:     {success_count}")
    log(f"Failed/Error:               {failure_count}")
    log(f"Elapsed time:               {elapsed:.2f}s ({elapsed/60:.2f} minutes)")
    log(f"\nFull results written to:    {results_file}")
    log("=" * 80)

    return final_results


if __name__ == "__main__":
    try:
        results = asyncio.run(main())
    except Exception as e:
        log(f"\nFATAL ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
