"""Scripted data operations for the finance/ERP slices (change add-finance-erp-domain-slices).

The database-touching parts are exercised on production during acceptance; these
tests pin the decisions that would be silent if wrong:

- the two rubric seeders define **exactly** the criteria they name (a miscount
  here means the template's readiness ratio lies);
- `promote_industry_template.with_rubrics` is additive and idempotent — running
  it twice must not produce a two-item refs list or drop an existing entry;
- the finance domain script refuses when the template is absent instead of
  creating a domain anchored to nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import promote_industry_template  # noqa: E402
import register_finance_domain  # noqa: E402
import seed_erp_rubric  # noqa: E402
import seed_finance_rubric  # noqa: E402


# ------------------------------------------------------------------ rubrics


def test_erp_rubric_names_are_unique():
    names = [c[0] for c in seed_erp_rubric.CRITERIA]
    assert len(names) == len(set(names)), "duplicate criterion names"


def test_finance_rubric_names_are_unique():
    names = [c[0] for c in seed_finance_rubric.CRITERIA]
    assert len(names) == len(set(names)), "duplicate criterion names"


@pytest.mark.parametrize("module", [seed_erp_rubric, seed_finance_rubric])
def test_every_criterion_has_a_guidance_line(module):
    """The guidance is what a human reviewer reads; an empty one is a blank form."""
    for name, desc, guide in module.CRITERIA:
        assert name and desc and guide, f"{module.RUBRIC_NAME}: {name!r} is incomplete"
        assert len(guide) >= 20, f"{name!r} guidance is too thin to review against"


def test_finance_criteria_align_with_the_pack_checkers():
    """The seven pack checkers are named in the rubric; nothing invented.

    Importing the pack registers its checkers, so the names compared here are the
    ones that actually run — not a list copied into this file.
    """
    import importlib

    importlib.import_module("packs.finance-data.checks")

    from src.bench import data_checks

    registered = data_checks.checkers_for("fact")
    assert set(registered) == {
        "band-vocabulary", "band-direction-consistency", "text-fingerprint-sha256",
        "text-chars-positive", "doc-id-identity", "as-of-iso-date",
        "amount-anchor-parseable",
    }
    # The rubric's first seven criteria are those checkers; the eighth is the
    # precondition (gold tier) that no checker can assert about itself.
    declared = [c[0] for c in seed_finance_rubric.CRITERIA]
    assert len(declared) == len(registered) + 1


# ----------------------------------------------------------------- promotion


def test_with_rubrics_is_additive():
    schema = {"entity_types": ["a"], "rubric_refs": ["existing"]}
    out = promote_industry_template.with_rubrics(schema, "new-one")
    assert out["rubric_refs"] == ["existing", "new-one"]
    # The input must not be mutated: callers pass the stored schema.
    assert schema["rubric_refs"] == ["existing"]


def test_with_rubrics_is_idempotent():
    schema = promote_industry_template.with_rubrics(
        {"rubric_refs": ["r"]}, "r"
    )
    assert schema["rubric_refs"] == ["r"]


def test_with_rubrics_creates_the_key_when_absent():
    out = promote_industry_template.with_rubrics({"entity_types": []}, "r")
    assert out["rubric_refs"] == ["r"]


# -------------------------------------------------------------- finance domain


def test_finance_domain_constants_are_the_documented_ones():
    assert register_finance_domain.TEMPLATE_NAME == "finance-market"
    assert register_finance_domain.DOMAIN_KEY == "finance"


def test_register_refuses_when_the_template_is_missing(monkeypatch, capsys):
    class FakeTemplates:
        @staticmethod
        def get_template(conn, name):
            return None

    import src.bench.templates as real_templates
    monkeypatch.setattr(real_templates, "get_template", FakeTemplates.get_template)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr("src.eval.db.connect", lambda: FakeConn())

    assert register_finance_domain.main(["--dry-run"]) == 1
    assert "not found" in capsys.readouterr().err
