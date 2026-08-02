#!/usr/bin/env python3
"""Extract batch pipeline results from database and generate report."""
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, 'src')

from src.eval.pipeline_store import list_pipeline_runs
from src.contracts.templates import list_contract_types


def main():
    print("=" * 80)
    print("Extracting Batch Pipeline Results from Database")
    print("=" * 80)

    # Get all contract types
    contract_types_list = list_contract_types()
    all_contract_types = [ct["key"] for ct in contract_types_list]
    print(f"\nTotal contract types: {len(all_contract_types)}")

    # Get all pipeline runs
    runs = list_pipeline_runs(limit=500)
    print(f"Total pipeline runs in database: {len(runs)}")

    # Group by contract type and get latest run for each
    contract_results = {}
    for r in runs:
        ct = r['contract_type']
        if ct not in contract_results:
            contract_results[ct] = r
        else:
            # Keep the latest run (highest ID)
            if r['id'] > contract_results[ct]['id']:
                contract_results[ct] = r

    print(f"Contract types with pipeline runs: {len(contract_results)}")

    # Build final results
    final_results = {}
    success_count = 0
    failure_count = 0

    for ct in all_contract_types:
        if ct in contract_results:
            r = contract_results[ct]
            final_results[ct] = {
                "pipeline_run_id": r['id'],
                "eval_run_id": r.get('eval_run_id'),
                "score": r.get('score'),
                "n_passed": r.get('n_passed'),
                "n_criteria": r.get('n_criteria'),
                "all_pass": bool(r.get('all_pass')),
                "iteration": r.get('iteration', 1),
                "subject": None,  # Not stored in database
                "party_a": None,  # Not stored in database
                "party_b": None,  # Not stored in database
                "fill_values": r.get('fill_values', {}),
                "filled_text_preview": (r.get('filled_text', '') or '')[:200] + "... (truncated)" if r.get('filled_text') else "",
                "status": "success",
            }
            success_count += 1
        else:
            final_results[ct] = {
                "status": "not_run",
                "error": "No pipeline run found for this contract type"
            }
            failure_count += 1

    # Write results to JSON file
    output_dir = Path(__file__).parent / "output" / "batch_pipeline_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "results.json"

    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": len(all_contract_types),
                "success": success_count,
                "failure": failure_count,
                "extracted_at": datetime.now().isoformat(),
                "parameters": {
                    "stance": "balanced",
                    "scenario": "一般",
                    "max_iterations": 2,
                    "temperature": 0.0,
                },
            },
            "results": final_results,
        }, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)

    for ct in all_contract_types:
        if ct in final_results and final_results[ct]["status"] == "success":
            r = final_results[ct]
            score_str = f"{r['score']:.1f}" if isinstance(r['score'], (int, float)) and r['score'] is not None else "N/A"
            status_str = "ALL PASS ✓" if r["all_pass"] else f"passed={r['n_passed']}/{r['n_criteria']}"
            print(f"[OK]   {ct:30s} score={score_str:>6} {status_str} iter={r['iteration']}")
        else:
            print(f"[FAIL] {ct:30s} {final_results[ct].get('error', 'Unknown error')}")

    print("\n" + "=" * 80)
    print("EXTRACTION COMPLETE")
    print("=" * 80)
    print(f"Total contract types: {len(all_contract_types)}")
    print(f"Successfully extracted: {success_count}")
    print(f"Missing/Failed:         {failure_count}")
    print(f"\nResults written to: {results_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
