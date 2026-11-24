"""What can be machine-checked about one unit, right now.

Background: the promotion page asked a person to decide "is this unit good
enough to move up" from nothing. Every other domain pack (erp / finance / gov)
already ships deterministic checkers, so their data at least had machine
verdicts to stand on; legal shipped none, and its 5,000 clauses could only be
promoted on vibes.

This module closes that gap at the point of decision, not in a batch job:

- :func:`checks_for_unit` runs the registered checkers for a unit's kind
  **against the unit's current body** and returns one verdict per checker. It
  is pure and cheap (string work only), so the promotion page can call it per
  row.
- :func:`summarise` folds those verdicts into the one thing an operator needs:
  can every mechanically checkable thing be said to pass, and if not, which
  ones.

What this deliberately does NOT do: decide whether to promote. A checker
passing means "nothing mechanically wrong was found", never "this is correct
law". The human keeps the judgement; this only removes the part they were
doing by hand and getting wrong (measured 2026-11-24: 23% of the legal corpus
is character-fragmented, which no one was catching by eye).
"""

from __future__ import annotations

from typing import Any, Optional

from . import data_checks


def checks_for_unit(unit: dict) -> list[dict]:
    """Run every checker registered for this unit's kind, against this unit.

    Returns ``[{name, passed, detail}]`` in registration order. A kind with no
    checkers yields ``[]`` — an honest "nothing is mechanically checkable here"
    rather than a fabricated pass.
    """
    kind = unit.get("kind")
    if not kind:
        return []
    out: list[dict] = []
    for name, fn in data_checks.checkers_for(kind).items():
        try:
            result = data_checks._coerce_result(name, fn(unit))
        except Exception as exc:  # noqa: BLE001 - a broken checker must say so
            # A checker that raises is a defect in the checker, and it must not
            # read as either a pass or a silent absence. Surfacing the error as
            # a failed verdict makes it visible on the row that triggered it.
            out.append({
                "name": name,
                "passed": False,
                "detail": f"检查器出错：{type(exc).__name__}: {exc}",
                "error": True,
            })
            continue
        out.append({
            "name": result.name,
            "passed": bool(result.passed),
            "detail": result.detail,
        })
    return out


def summarise(checks: list[dict]) -> dict:
    """Fold check verdicts into the one line the promotion row shows.

    ``{"checkable": bool, "passed": int, "total": int, "all_pass": bool,
       "failed_names": [str]}``

    ``checkable`` is false when the kind has no checkers — the caller must show
    "nothing is mechanically checkable" and must NOT render ``all_pass``, or a
    domain with no checkers silently looks like a domain where everything is
    verified.
    """
    if not checks:
        return {"checkable": False, "passed": 0, "total": 0,
                "all_pass": False, "failed_names": []}
    total = len(checks)
    passed = sum(1 for c in checks if c["passed"])
    return {
        "checkable": True,
        "passed": passed,
        "total": total,
        "all_pass": passed == total,
        "failed_names": [c["name"] for c in checks if not c["passed"]],
    }
