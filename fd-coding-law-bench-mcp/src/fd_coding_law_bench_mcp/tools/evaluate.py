"""``evaluate_contract`` / ``list_rubrics`` / ``list_runs`` tools.

Wraps the LLM-judge rubric evaluator in :mod:`src.eval`. ``evaluate_contract``
accepts either a file path or inline contract text, and persists the run to the
eval DB unless ``no_store`` is set.
"""

from __future__ import annotations

from pathlib import Path

from ..server import mcp


@mcp.tool
def evaluate_contract(
    contract: str,
    rubric: str,
    task: str | None = None,
    no_store: bool = False,
    verbose: bool = False,
) -> dict:
    """Evaluate a drafted contract against a named rubric (LLM-judge).

    Parameters:
        contract: path to a drafted contract file, OR inline contract text. If
            the value points at an existing file it is read; otherwise it is
            treated as the contract text itself.
        rubric: rubric name, e.g. ``"contract_drafting_v1"``.
        task: optional original user request / task description, passed to the
            judge as input context.
        no_store: when True, do not persist the run to the eval database.
        verbose: verbose judge output.

    Returns ``{rubric, judge_model, score, max_score, all_pass, n_passed,
    n_criteria, summary, criteria_results, scored_at}``. A missing rubric or
    unreadable contract raises a tool error.
    """
    from src.eval.scoring import evaluate_contract as _evaluate
    from src.eval.store import store_result

    path = Path(contract)
    if path.is_file():
        contract_text = path.read_text(encoding="utf-8")
        contract_path = str(path)
    else:
        contract_text = contract
        contract_path = None

    result = _evaluate(
        contract_text,
        rubric,
        task_desc=task,
        verbose=verbose,
    )

    if not no_store:
        store_result(result, contract_path=contract_path, task_desc=task)

    return result


@mcp.tool
def list_rubrics() -> list[dict]:
    """List available evaluation rubrics as ``{name, context, source}``."""
    from src.eval.rubric import list_rubrics as _list_rubrics

    return _list_rubrics()


@mcp.tool
def list_runs(limit: int = 20) -> list[dict]:
    """List recent evaluation runs (most recent first)."""
    from src.eval.store import list_runs as _list_runs

    return _list_runs(limit=limit)
