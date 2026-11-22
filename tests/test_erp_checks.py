"""ERP account checkers (packs/erp/checks.py).

Two deterministic validity invariants over ``kind='account'`` units. Each test
proves both directions on a **real-format** unit (an ``account:<code>`` key with
the ``attrs`` the import scripts actually write — see
``scripts/import_account_mapping_crosswalks.py``), so the checker is shown to
fire, not just to exist. The production distribution (23/23 pass on clean data;
a bad import fails) is recorded in the change's ``acceptance.md`` and is the
``criterion-must-fire-on-real-data`` evidence for these invariants.
"""

from __future__ import annotations

import packs.erp.checks as erp


def _account(maps_to="4000", *, evidence=True):
    attrs = {"maps_to": maps_to, "vertical": "restaurant-chain", "industry_code": "R-0001"}
    if evidence:
        attrs["evidence"] = {
            "quote": "R-0001 门店营业收入 → 4000",
            "source_path": "templates/restaurant-chain/account-mapping/pack.json",
        }
    return {"kind": "account", "external_key": "account:R-0001", "attrs": attrs}


def test_maps_to_preset_passes_on_in_vocabulary_code():
    res = erp.check_account_maps_to_preset(_account(maps_to="4000"))
    assert res.passed is True


def test_maps_to_preset_fails_on_out_of_vocabulary_code():
    res = erp.check_account_maps_to_preset(_account(maps_to="9999"))
    assert res.passed is False
    assert "9999" in res.detail


def test_maps_to_preset_fails_when_missing():
    unit = {"kind": "account", "external_key": "account:X", "attrs": {}}
    assert erp.check_account_maps_to_preset(unit).passed is False


def test_maps_to_preset_fails_on_non_string_code():
    # a numeric 4000 must not pass the string membership test by coercion
    assert erp.check_account_maps_to_preset(_account(maps_to=4000)).passed is False


def test_evidence_anchor_passes_with_quote_and_source():
    assert erp.check_account_evidence_anchor(_account(evidence=True)).passed is True


def test_evidence_anchor_fails_without_evidence():
    assert erp.check_account_evidence_anchor(_account(evidence=False)).passed is False


def test_evidence_anchor_fails_on_incomplete_evidence():
    unit = _account(evidence=False)
    unit["attrs"]["evidence"] = {"quote": "x"}  # no source_path
    assert erp.check_account_evidence_anchor(unit).passed is False


def test_checkers_register_on_import():
    from src.bench import data_checks

    import packs.erp  # noqa: F401  (import-time registration)

    names = set(data_checks.checkers_for("account"))
    assert {"account-maps-to-preset", "account-evidence-anchor"} <= names
