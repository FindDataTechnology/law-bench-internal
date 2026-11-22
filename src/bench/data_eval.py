"""Run a domain's deterministic data evaluation and attribute it to the domain.

``data_checks.run_data_eval`` evaluates units of one kind and writes a
``channel='data'`` conclusion — but it needs to know *which* units and, for the
domain matrix to see the result, *which domain* owns the ruler. This module is
the thin domain-scoped wrapper that answers both, reusing ``run_data_eval``'s
aggregation and verdict identity so there is one definition of "a data-channel
evaluation" (change deepen-industry-lines D2).

Scope of a run, for a domain:

- the domain's namespace is its ``key`` (``authoring`` writes every unit there);
- the kinds are the ones the domain's **pack** declares *and* for which a
  checker is registered in this process (``data_checks.checkers_for(kind)``).
  A pack that declares a kind with no checker simply contributes nothing — that
  is an honest "not evaluable yet", not a silent zero. This process must have
  imported the pack (``packs.<line>``) for its checkers to exist; the web app
  imports them at its edge (``src/web/routes/console.py``), like the kernel-
  purity gate requires.

An empty selection (no live units of any evaluable kind) yields an
``inconclusive`` conclusion per ``run_data_eval`` — never a fabricated pass.
"""

from __future__ import annotations

from typing import Any, Optional

from src.settings import DEFAULT_DB

from . import data_checks, packs, store, workspaces


def evaluable_kinds(domain_key: str) -> list[str]:
    """Kinds the domain's pack declares that have a checker registered here.

    No pack (or a pack file that will not load) means "no declared kinds" — the
    caller reports inconclusive rather than raising, because a domain without a
    pack is a legitimate state (it simply has no deterministic channel yet).
    """
    try:
        manifest = packs.load_pack(domain_key)
    except (FileNotFoundError, ValueError):
        return []
    declared = manifest.get("kinds") or []
    return [k for k in declared if data_checks.checkers_for(k)]


def run_domain_data_eval(
    conn: Any,
    *,
    domain_key: str,
    kind: Optional[str] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Evaluate a domain's live units of ``kind`` (or every evaluable kind).

    Returns a summary dict ``{domain_key, kinds, run_ids, n_units, n_criteria,
    n_passed, outcome}``. When ``kind`` is a specific evaluable kind only that
    kind runs; otherwise every evaluable kind runs and their per-kind conclusions
    are all stored (each attributed to the domain). If there are no evaluable
    kinds at all, nothing is stored and the summary is ``outcome='inconclusive'``
    with ``run_ids=[]`` — the page shows "nothing to evaluate", not a zero.
    """
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")

    evaluable = evaluable_kinds(domain_key)
    if kind is not None:
        if kind not in evaluable:
            raise ValueError(
                f"kind {kind!r} is not evaluable in domain {domain_key!r} "
                f"(evaluable: {evaluable})"
            )
        kinds = [kind]
    else:
        kinds = evaluable

    run_ids: list[int] = []
    n_units_total = 0
    for k in kinds:
        # Live units of this kind in the domain namespace; the checker only sees
        # the ones that actually exist, so an empty list means inconclusive.
        unit_ids = [
            u["external_key"]
            for u in store.list_knowledge_units(
                conn, kind=k, namespace=domain["key"], include_deleted=False,
                limit=store.MAX_LIST_UNITS,
            )
        ]
        n_units_total += len(unit_ids)
        run_id = data_checks.run_data_eval(
            conn,
            kind=k,
            unit_ids=unit_ids,
            db_path=db_path,
            rubric_domain_id=domain["id"],
        )
        run_ids.append(run_id)

    if not run_ids:
        return {
            "domain_key": domain_key,
            "kinds": [],
            "run_ids": [],
            "n_units": 0,
            "n_criteria": 0,
            "n_passed": 0,
            "outcome": "inconclusive",
        }

    # Read the just-written runs back so the summary's numbers and outcome are the
    # stored ones, not a recomputation that could drift from what landed.
    from src.eval.store import get_run

    n_criteria_total = n_passed_total = 0
    outcomes: list[str] = []
    for rid in run_ids:
        run = get_run(rid, db_path=db_path)
        n_criteria_total += run["n_criteria"]
        n_passed_total += run["n_passed"]
        outcomes.append(run["outcome"])
    # Inconclusive if any component was; otherwise pass only when all passed.
    if "inconclusive" in outcomes:
        outcome = "inconclusive"
    elif all(o == "pass" for o in outcomes):
        outcome = "pass"
    else:
        outcome = "fail"

    return {
        "domain_key": domain_key,
        "kinds": kinds,
        "run_ids": run_ids,
        "n_units": n_units_total,
        "n_criteria": n_criteria_total,
        "n_passed": n_passed_total,
        "outcome": outcome,
    }
