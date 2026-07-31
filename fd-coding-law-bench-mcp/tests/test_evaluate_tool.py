"""Tests for ``evaluate_contract`` / ``list_rubrics`` / ``list_runs``.

Hermetic: the wrapped ``src.eval`` functions are monkeypatched (no LLM judge, no
DB). Verifies file-or-text dispatch, ``no_store`` behavior, error propagation,
and the list helpers.
"""

from __future__ import annotations

import pytest


def _eval_result(**over):
    base = {
        "rubric": "contract_drafting_v1",
        "score": 1.0,
        "max_score": 1.0,
        "all_pass": True,
        "n_criteria": 2,
        "n_passed": 2,
        "summary": "2/2 criteria passed. ALL PASS.",
        "criteria_results": [
            {"id": "c1", "title": "t", "verdict": "pass", "reasoning": ""}
        ],
        "judge_model": "ark",
        "scored_at": "2026-07-31T00:00:00Z",
    }
    base.update(over)
    return base


def test_inline_text_no_store(monkeypatch):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    calls = {}

    def fake_eval(contract_text, rubric_name, task_desc=None, verbose=False):
        calls.update(text=contract_text, rubric=rubric_name, task=task_desc, verbose=verbose)
        return _eval_result()

    store_calls: list = []
    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_eval)
    monkeypatch.setattr(store_mod, "store_result", lambda *a, **k: store_calls.append((a, k)) or 1)

    from fd_coding_law_bench_mcp.tools.evaluate import evaluate_contract

    res = evaluate_contract("# 服务协议\n甲方...", "contract_drafting_v1", task="起草", no_store=True)
    assert calls["text"].startswith("# 服务协议")
    assert calls["rubric"] == "contract_drafting_v1"
    assert calls["task"] == "起草"
    assert store_calls == []  # no_store -> nothing persisted
    assert res["all_pass"] is True
    assert res["criteria_results"][0]["verdict"] == "pass"


def test_file_path_is_read_and_stored(monkeypatch, tmp_path):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    draft = tmp_path / "draft.md"
    draft.write_text("# 合同正文", encoding="utf-8")

    seen = {}

    def fake_eval(contract_text, rubric_name, task_desc=None, verbose=False):
        seen["text"] = contract_text
        return _eval_result()

    store_args = {}

    def fake_store(result, contract_path=None, task_desc=None):
        store_args.update(contract_path=contract_path, task_desc=task_desc)
        return 42

    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_eval)
    monkeypatch.setattr(store_mod, "store_result", fake_store)

    from fd_coding_law_bench_mcp.tools.evaluate import evaluate_contract

    evaluate_contract(str(draft), "contract_drafting_v1", task="t")
    assert seen["text"] == "# 合同正文"
    assert store_args["contract_path"] == str(draft)
    assert store_args["task_desc"] == "t"


def test_missing_rubric_propagates(monkeypatch):
    import src.eval.scoring as scoring_mod

    def boom(contract_text, rubric_name, task_desc=None, verbose=False):
        raise KeyError(f"Rubric not found: {rubric_name!r}")

    monkeypatch.setattr(scoring_mod, "evaluate_contract", boom)

    from fd_coding_law_bench_mcp.tools.evaluate import evaluate_contract

    with pytest.raises(KeyError):
        evaluate_contract("some text", "not_a_rubric")


def test_list_rubrics_and_runs(monkeypatch):
    import src.eval.rubric as rubric_mod
    import src.eval.store as store_mod

    monkeypatch.setattr(
        rubric_mod,
        "list_rubrics",
        lambda db_path=None: [{"name": "r1", "context": "check", "source": "s"}],
    )
    monkeypatch.setattr(store_mod, "list_runs", lambda limit=20, db_path=None: [{"id": 1}])

    from fd_coding_law_bench_mcp.tools.evaluate import list_rubrics, list_runs

    assert list_rubrics() == [{"name": "r1", "context": "check", "source": "s"}]
    assert list_runs(limit=5) == [{"id": 1}]
