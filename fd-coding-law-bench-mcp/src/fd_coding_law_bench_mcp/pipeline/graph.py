"""LangGraph contract-pipeline: generate -> fill -> evaluate -> (self-heal) -> store.

Hosted inside the ``pipeline_run`` MCP tool (B+). Nodes call the existing MCP
tool **functions** (``contract_generate``, ``contract_evaluate``, ``clause_list``)
in-process, plus the LLM ``fill`` / ``improve`` nodes and ``pipeline_store``. The
self-heal loop excludes thin custom clauses **per run** (via ``custom_clause_ids``)
and records ``clause_review`` recommendations without executing them.
"""

from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class PipelineState(TypedDict, total=False):
    contract_type: str
    tags: dict
    stance: str | None
    rubric: str
    task_desc: str | None
    fill_mode: str
    temperature: float
    max_iterations: int
    custom_clause_ids: list[int] | None
    iteration: int
    gen_result: dict
    body_text: str
    slots: list[str]
    instructions: list[dict]
    filled_text: str
    fill_values: dict
    fill_cache_id: int | None
    fill_temperature: float | None
    unfilled_slots: list[str]
    eval_result: dict
    eval_run_id: int | None
    best: dict
    excluded_ids: list[int]
    actions_taken: list
    recommendations: list
    pipeline_run_id: int


def default_rubric(contract_type: str) -> str:
    """Latest-version rubric for ``contract_type``: highest ``v<N>`` among
    ``contract_<type>_v<N>`` names, else alphabetically-last ``contract_<type>_*``
    name; raise :class:`NotFoundError` if none."""
    from src.eval.errors import NotFoundError
    from src.eval.rubric import list_rubrics

    names = [r["name"] for r in list_rubrics()]
    pat = re.compile(rf"^contract_{re.escape(contract_type)}_v(\d+)$")
    versioned = [(int(m.group(1)), n) for n in names if (m := pat.match(n))]
    if versioned:
        return max(versioned)[1]
    prefixed = sorted(n for n in names if n.startswith(f"contract_{contract_type}_"))
    if prefixed:
        return prefixed[-1]
    raise NotFoundError(
        f"no rubric found for contract type {contract_type!r}; pass rubric= explicitly"
    )


def _current_customs(contract_type: str, stance: str | None) -> list[dict]:
    """Assembly-ready custom clauses matching ``stance`` (the per-section overrides)."""
    from ..tools.clauses import clause_list
    from src.clauses.tag_review import is_assembly_ready

    rows = clause_list(contract_type, category="custom", tags=({"stance": stance} if stance else None))
    return [c for c in rows if is_assembly_ready(c)]


# --- nodes ---


def generate_node(state: PipelineState) -> dict:
    from ..tools.generate import contract_generate

    res = contract_generate(
        state["contract_type"],
        format="docx",
        tags=state.get("tags"),
        stance=state.get("stance"),
        custom_clause_ids=state.get("custom_clause_ids"),
    )
    return {
        "gen_result": res,
        "body_text": res.get("body_text") or "",
        "slots": res.get("slots") or [],
        "instructions": res.get("instructions") or [],
    }


def fill_node(state: PipelineState) -> dict:
    from .fill import fill_slots, render_filled

    scenario = (state.get("tags") or {}).get("scenario")
    fr = fill_slots(
        state["contract_type"],
        scenario,
        state["slots"],
        state["instructions"],
        state.get("temperature", 0.0),
        state.get("task_desc"),
    )
    filled, unfilled = render_filled(state["body_text"], fr["fill_values"])
    return {
        "filled_text": filled,
        "fill_values": fr["fill_values"],
        "fill_cache_id": fr["fill_cache_id"],
        "fill_temperature": fr.get("temperature"),
        "unfilled_slots": unfilled,
    }


def evaluate_node(state: PipelineState) -> dict:
    from ..tools.evaluate import contract_evaluate

    res = contract_evaluate(state["filled_text"], state["rubric"], state.get("task_desc"))
    return {"eval_result": res, "eval_run_id": res.get("run_id")}


def _rank(ev: dict) -> tuple[int, float]:
    return (int(ev.get("n_passed") or 0), float(ev.get("score") or 0.0))


def check_node(state: PipelineState) -> dict:
    cur = state["eval_result"]
    best = state.get("best")
    if best is None or _rank(cur) > _rank(best.get("eval_result", {})):
        best = {
            "n_passed": cur.get("n_passed"),
            "score": cur.get("score"),
            "iteration": state.get("iteration", 1),
            "filled_text": state["filled_text"],
            "fill_values": state["fill_values"],
            "eval_result": cur,
            "eval_run_id": state.get("eval_run_id"),
            "fill_cache_id": state.get("fill_cache_id"),
            "fill_temperature": state.get("fill_temperature"),
        }
    return {"best": best}


def _route(state: PipelineState) -> str:
    if state["eval_result"].get("all_pass") or state.get("iteration", 1) >= state.get("max_iterations", 3):
        return "store"
    return "improve"


def improve_node(state: PipelineState) -> dict:
    from .improve import diagnose

    failing = [c for c in state["eval_result"].get("criteria_results", []) if c.get("verdict") != "pass"]
    stance = state.get("stance")
    customs = _current_customs(state["contract_type"], stance)
    diag = diagnose(
        state["contract_type"],
        (state.get("tags") or {}).get("scenario"),
        stance,
        failing,
        customs,
    )
    new_excl = diag.get("exclude_custom_clause_ids", [])
    excluded = list(dict.fromkeys((state.get("excluded_ids") or []) + new_excl))
    full_ids = [c["id"] for c in customs]
    new_custom = [i for i in full_ids if i not in excluded]
    recs = diag.get("recommendations", [])
    actions = (state.get("actions_taken") or []) + [
        {
            "iteration": state.get("iteration", 1),
            "failing": [f.get("title") for f in failing],
            "excluded": new_excl,
            "recommendations": recs,
        }
    ]
    return {
        "excluded_ids": excluded,
        "custom_clause_ids": new_custom,
        "actions_taken": actions,
        "recommendations": (state.get("recommendations") or []) + recs,
        "iteration": state.get("iteration", 1) + 1,
    }


def store_node(state: PipelineState) -> dict:
    from src.eval.pipeline_store import insert_pipeline_run

    best = state.get("best") or {}
    ev = best.get("eval_result") or state.get("eval_result") or {}
    row = {
        "contract_type": state["contract_type"],
        "tags": state.get("tags") or {},
        "stance": state.get("stance"),
        "rubric_name": state["rubric"],
        "task_desc": state.get("task_desc"),
        "fill_mode": state.get("fill_mode", "llm"),
        "fill_values": best.get("fill_values") or state.get("fill_values") or {},
        "filled_text": best.get("filled_text") or state.get("filled_text"),
        "eval_run_id": best.get("eval_run_id") or state.get("eval_run_id"),
        "score": ev.get("score"),
        "max_score": ev.get("max_score"),
        "n_passed": ev.get("n_passed"),
        "n_criteria": ev.get("n_criteria"),
        "all_pass": int(bool(ev.get("all_pass"))),
        "iteration": best.get("iteration") or state.get("iteration", 1),
        "actions_taken": state.get("actions_taken") or [],
        "recommendations": state.get("recommendations") or [],
        "fill_cache_id": best.get("fill_cache_id") or state.get("fill_cache_id"),
        "fill_temperature": (
            best.get("fill_temperature")
            if best.get("fill_temperature") is not None
            else state.get("fill_temperature")
        ),
    }
    pid = insert_pipeline_run(row)
    return {"pipeline_run_id": pid}


def build_graph():
    """Compile and return the pipeline StateGraph."""
    g = StateGraph(PipelineState)
    g.add_node("generate", generate_node)
    g.add_node("fill", fill_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("check", check_node)
    g.add_node("improve", improve_node)
    g.add_node("store", store_node)
    g.add_edge(START, "generate")
    g.add_edge("generate", "fill")
    g.add_edge("fill", "evaluate")
    g.add_edge("evaluate", "check")
    g.add_conditional_edges("check", _route, {"store": "store", "improve": "improve"})
    g.add_edge("improve", "generate")
    g.add_edge("store", END)
    return g.compile()


def run_pipeline(
    contract_type: str,
    tags: dict | None = None,
    stance: str | None = None,
    rubric: str | None = None,
    task_desc: str | None = None,
    fill_mode: str = "llm",
    temperature: float = 0.0,
    max_iterations: int = 3,
    custom_clause_ids: list[int] | None = None,
) -> dict:
    """Run the pipeline graph; return the final state (incl. ``pipeline_run_id``)."""
    if rubric is None:
        rubric = default_rubric(contract_type)
    if stance is None:
        stance = (tags or {}).get("stance")
    initial: dict = {
        "contract_type": contract_type,
        "tags": tags or {},
        "stance": stance,
        "rubric": rubric,
        "task_desc": task_desc,
        "fill_mode": fill_mode,
        "temperature": temperature,
        "max_iterations": max_iterations,
        "custom_clause_ids": custom_clause_ids,
        "iteration": 1,
        "excluded_ids": [],
        "actions_taken": [],
        "recommendations": [],
    }
    return build_graph().invoke(initial)
