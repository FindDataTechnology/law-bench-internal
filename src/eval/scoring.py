"""Evaluate a drafted contract against a rubric using deepeval's native GEval
LLM-judge, mirroring harvey-labs' all-pass rubric methodology.

harvey-labs (`evaluation/scoring.py`):
  - one LLM-judge call per criterion -> binary pass/fail verdict + reasoning
  - criteria are judged concurrently via ThreadPoolExecutor
  - task scores 1.0 ONLY if every criterion passed (all-pass); else 0.0
  - records n_criteria / n_passed diagnostics and per-criterion results

deepeval mapping (no hand-rolled prompt; uses deepeval's base GEval ability):
  - one GEval(strict_mode=True) per criterion, `criteria` = the criterion's
    guidance (== harvey-labs match_criteria). strict_mode forces binary 1/0 and
    threshold=1, so each metric's success == pass/fail verdict.
  - like harvey-labs, we call each criterion's judge directly (GEval.measure)
    in a thread pool and aggregate, rather than going through deepeval's
    evaluate() test-runner (which mis-times-out against the Ark endpoint).
  - results are read straight off the GEval instances (mutated in place).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from src.settings import DEFAULT_DB

from .judge import get_judge
from .rubric import load_criteria


def _build_metrics(criteria: list[dict], judge, include_input: bool) -> list[GEval]:
    """One GEval per criterion, strict (binary) judging against its guidance."""
    params = [LLMTestCaseParams.ACTUAL_OUTPUT]
    if include_input:
        params.append(LLMTestCaseParams.INPUT)

    metrics: list[GEval] = []
    for c in criteria:
        metrics.append(
            GEval(
                name=c["id"],
                criteria=c["match_criteria"],
                evaluation_params=params,
                strict_mode=True,  # binary pass(1)/fail(0); threshold forced to 1
                model=judge,
                async_mode=False,  # we drive execution ourselves (sync measure)
            )
        )
    return metrics


def evaluate_contract(
    contract_text: str,
    rubric_name: str,
    task_desc: Optional[str] = None,
    judge=None,
    verbose: bool = False,
    max_workers: int = 8,
    db_path=DEFAULT_DB,
) -> dict:
    """Score a drafted contract against a named rubric; return a scores dict.

    The returned dict follows harvey-labs' scores.json shape (score, all_pass,
    n_criteria, n_passed, criteria_results, judge_model, scored_at) so output
    stays comparable to a harvey-labs run.

    ``db_path`` defaults to the project DB; tests pass a throwaway DB so they do
    not touch the development database.
    """
    criteria = load_criteria(rubric_name, db_path=db_path)  # raises KeyError / ValueError if bad
    judge = judge or get_judge()

    include_input = bool(task_desc)
    test_case = LLMTestCase(
        input=task_desc or "",
        actual_output=contract_text,
    )
    metrics = _build_metrics(criteria, judge, include_input)

    # Judge each criterion concurrently (mirrors harvey-labs' ThreadPoolExecutor).
    def _score_one(metric: GEval) -> None:
        try:
            metric.measure(test_case, _show_indicator=False)
        except Exception as e:  # one bad judge call must not sink the run
            metric.error = str(e)

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(metrics)))) as pool:
        list(pool.map(_score_one, metrics))

    criteria_results = []
    for c, g in zip(criteria, metrics):
        err = getattr(g, "error", None)
        success = bool(getattr(g, "success", False))
        criteria_results.append(
            {
                "id": c["id"],
                "title": c["title"],
                "verdict": "pass" if success else "fail",
                "reasoning": (getattr(g, "reason", "") or "")
                + (f" [error: {err}]" if err else ""),
            }
        )

    n_total = len(criteria_results)
    n_passed = sum(1 for r in criteria_results if r["verdict"] == "pass")
    all_pass = n_passed == n_total

    return {
        "rubric": rubric_name,
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "all_pass": all_pass,
        "n_criteria": n_total,
        "n_passed": n_passed,
        "summary": (
            f"{n_passed}/{n_total} criteria passed. ALL PASS."
            if all_pass
            else f"{n_passed}/{n_total} criteria passed. Missed {n_total - n_passed} - FAIL."
        ),
        "criteria_results": criteria_results,
        "judge_model": getattr(metrics[0], "evaluation_model", None)
        or os.environ.get("EVAL_MODEL"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
