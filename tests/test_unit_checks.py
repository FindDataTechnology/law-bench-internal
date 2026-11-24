"""Unit checks fold deterministic verdicts onto the promotion decision."""
from __future__ import annotations

import pytest

from src.bench import data_checks, unit_checks


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(data_checks._CHECKERS)
    data_checks._CHECKERS.clear()
    yield
    data_checks._CHECKERS.clear()
    data_checks._CHECKERS.update(saved)


def test_no_checkers_is_not_a_pass():
    """A kind with no checkers must say "not checkable", never "all pass".

    This is the failure that makes a gate worthless: a domain where nothing is
    checked would otherwise look like a domain where everything passed.
    """
    s = unit_checks.summarise(unit_checks.checks_for_unit({"kind": "nothing"}))
    assert s["checkable"] is False
    assert s["all_pass"] is False
    assert s["total"] == 0


def test_verdicts_fold_and_name_the_failures():
    data_checks.register_checker("k", "ok", lambda u: True)
    data_checks.register_checker("k", "bad", lambda u: False)
    s = unit_checks.summarise(
        unit_checks.checks_for_unit({"kind": "k", "body": "x"})
    )
    assert s["checkable"] is True
    assert (s["passed"], s["total"], s["all_pass"]) == (1, 2, False)
    assert s["failed_names"] == ["bad"]


def test_a_raising_checker_is_a_visible_failure_not_an_absence():
    """A broken checker must not silently disappear from the row.

    If it did, a checker with a bug would read as "nothing to check here" — the
    same shape as "everything passed" once it hits the page.
    """
    data_checks.register_checker("k", "boom", lambda u: 1 / 0)
    checks = unit_checks.checks_for_unit({"kind": "k"})
    assert len(checks) == 1
    assert checks[0]["passed"] is False
    assert checks[0].get("error") is True
    assert "ZeroDivisionError" in checks[0]["detail"]


def test_checks_run_against_the_units_current_body():
    """The verdict is recomputed from this unit, not read from a stale run."""
    data_checks.register_checker(
        "k", "nonempty", lambda u: bool((u.get("body") or "").strip())
    )
    ok = unit_checks.checks_for_unit({"kind": "k", "body": "有正文"})
    empty = unit_checks.checks_for_unit({"kind": "k", "body": "   "})
    assert ok[0]["passed"] is True
    assert empty[0]["passed"] is False
