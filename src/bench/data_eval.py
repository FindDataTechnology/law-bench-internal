"""Run a domain's deterministic data evaluation and attribute it to the domain.

``data_checks.run_data_eval`` evaluates units of one kind and writes a
``channel='data'`` conclusion — but it needs to know *which* units and, for the
domain matrix to see the result, *which domain* owns the ruler. This module is
the thin domain-scoped wrapper that answers both, reusing ``run_data_eval``'s
aggregation and verdict identity so there is one definition of "a data-channel
evaluation" (change deepen-industry-lines D2).

Scope of a run, for a domain:

- the domain's namespace is its ``key`` (``authoring`` writes every unit there);
- the kinds are the domain's **live unit kinds for which a checker is registered
  in this process** (``data_checks.checkers_for(kind)``). This is deliberately
  derived from the units that actually exist, not from a pack-name lookup:
  a domain key need not equal its pack directory (the ``finance`` domain is fed
  by the ``finance-data`` pack), so "call the pack after the domain" would miss
  the richest industry domain. "What can this domain actually be measured on" is
  answered by "which of its live kinds have a checker here".

A kind whose pack declares it but for which no checker is registered is simply
not evaluable — an honest "not measurable yet", not a silent zero. The process
must have imported the pack for its checkers to exist; the web app imports them
at its edge (``src/web/routes/console.py``), as the kernel-purity gate requires.

An empty selection (no live units of any evaluable kind) yields an
``inconclusive`` conclusion per ``run_data_eval`` — never a fabricated pass.
"""

from __future__ import annotations

from typing import Any, Optional

from src.settings import DEFAULT_DB

from . import data_checks, store, workspaces


def evaluable_kinds(conn: Any, *, domain_key: str) -> list[str]:
    """The domain's live unit kinds that have a checker registered here.

    Derived from stored units, not from a pack name, so a domain key that differs
    from its pack directory (``finance`` vs ``finance-data``) is still covered.
    Returns ``[]`` for an unknown domain (the caller reports inconclusive), and
    never raises on a domain that simply has nothing evaluable yet.

    One ``SELECT DISTINCT kind`` per render — not a full fetch of the domain's
    units (the legal domain holds thousands of clauses; listing them just to learn
    which kinds exist would make every page view slow).
    """
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        return []
    rows = conn.execute(
        "SELECT DISTINCT kind FROM knowledge_units "
        "WHERE namespace = %s AND COALESCE(tags->>'deleted', 'false') <> 'true'",
        (domain["key"],),
    ).fetchall()
    kinds = {r["kind"] if isinstance(r, dict) else r[0] for r in rows}
    return sorted(k for k in kinds if data_checks.checkers_for(k))


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

    evaluable = evaluable_kinds(conn, domain_key=domain_key)
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
