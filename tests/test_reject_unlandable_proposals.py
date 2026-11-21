"""The unlandable-proposal classifier judges structure, not modelling taste.

Change ``add-finance-erp-domain-slices``. Two rules only, each about something
that **cannot** work rather than something that looks wrong:

- a relationship whose evidence is not the dict the confirmation path reads;
- an ``entity:``-prefixed key, which key folding does not strip and which would
  therefore become a second unit for one dataset.

The third rule — duplicate claim — groups on kind + dataset + the key columns the
submitter measured, *not* on the dataset alone. Measured 2026-11-21: `#88` asserts
a three-column key and `#91` a two-column key for one dataset; collapsing those
would discard one claim the reader never saw.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reject_unlandable_proposals as tool  # noqa: E402


def prop(pid: int, *, kind: str, key: str, evidence) -> dict:
    return {"id": pid, "kind": kind, "external_key": key, "evidence": evidence}


# ------------------------------------------------------------------ structure


def test_relationship_with_string_evidence_is_unlandable():
    p = prop(1, kind="n:1", key="a.code->n:1:b.code",
             evidence=[{"from_key": "a.code"}])
    assert tool.classify(p) == "unlandable-evidence"


def test_relationship_with_dict_evidence_is_left_alone():
    p = prop(2, kind="n:1", key="a.code->n:1:b.code",
             evidence={"from_key": "a.code", "to_key": "b.code"})
    assert tool.classify(p) is None


def test_relationship_dict_without_endpoints_is_unlandable():
    p = prop(3, kind="n:1", key="a->n:1:b", evidence={"columns": ["code"]})
    assert tool.classify(p) == "unlandable-evidence"


def test_entity_prefixed_key_is_a_duplicate_identity():
    p = prop(4, kind="entity", key="entity:securities_company_financials",
             evidence={"dataset": "securities_company_financials"})
    assert tool.classify(p) == "duplicate-claim"


def test_plain_key_is_left_alone():
    p = prop(5, kind="entity", key="securities_company_financials",
             evidence={"dataset": "securities_company_financials"})
    assert tool.classify(p) is None


# --------------------------------------------------------------- duplicates


def test_same_claim_under_two_keys_keeps_the_richer_one():
    rich = prop(10, kind="entity", key="entity:ds",
                evidence={"dataset": "ds", "columns": ["code", "item"],
                          "check": "unique", "result": "90/90", "extra": "x" * 50})
    thin = prop(11, kind="entity", key="ds",
                evidence={"dataset": "ds", "columns": ["code", "item"]})
    _, keep = tool.collapse_duplicates([rich, thin])
    assert keep[10] == "kept"
    assert keep[11] == "duplicate-claim"


def test_different_claims_about_one_dataset_are_not_duplicates():
    """Three-column key vs two-column key: different assertions, both kept."""
    three = prop(20, kind="entity", key="ds",
                 evidence=[{"dataset": "ds", "columns": ["code", "item", "period"]}])
    two = prop(21, kind="entity", key="entity:ds",
               evidence=[{"dataset": "ds", "columns": ["series", "code", "name",
                                                       "item", "label", "period"]}])
    _, keep = tool.collapse_duplicates([three, two])
    assert 20 not in keep and 21 not in keep


def test_single_submission_is_never_a_duplicate():
    only = prop(30, kind="entity", key="ds", evidence={"dataset": "ds"})
    _, keep = tool.collapse_duplicates([only])
    assert keep == {}


def test_dataset_identity_is_read_from_a_list_payload_too():
    """`list_proposals` returns evidence decoded, so the list shape is the norm."""
    p = prop(40, kind="entity", key="ds",
             evidence=[{"dataset": "securities_industry_monitor"}])
    assert tool._dataset_of(p) == "securities_industry_monitor"
