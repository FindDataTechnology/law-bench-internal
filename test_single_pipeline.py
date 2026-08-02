#!/usr/bin/env python3
"""Test single pipeline run with immediate output."""
import sys
import time

print("Starting test...", flush=True)
sys.path.insert(0, 'fd-coding-law-bench-mcp/src')
sys.path.insert(0, 'src')

print("Paths added, importing...", flush=True)
from fd_coding_law_bench_mcp.pipeline.graph import run_pipeline

print("Import successful, running pipeline for 'sale'...", flush=True)
start = time.time()

result = run_pipeline(
    contract_type='sale',
    tags={'stance': 'balanced', 'scenario': '一般'},
    stance='balanced',
    task_desc='Test balanced sale contract',
    max_iterations=1,
    temperature=0.0,
)

elapsed = time.time() - start
print(f"\n✓ Pipeline completed in {elapsed:.1f}s", flush=True)
print(f"Pipeline run ID: {result.get('pipeline_run_id')}", flush=True)
print(f"Eval run ID: {result.get('eval_run_id')}", flush=True)
print(f"Score: {result.get('eval_result', {}).get('score')}", flush=True)
print(f"Passed: {result.get('eval_result', {}).get('n_passed')}/{result.get('eval_result', {}).get('n_criteria')}", flush=True)
