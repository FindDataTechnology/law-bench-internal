"""Nine-stage funnel: seven crawler stages plus two ontology ones.

The load-bearing distinctions:

- **landed ≠ mapped.** "We ingested the source" and "we know which part of the
  ontology it fills" have different remedies — an engineer versus a curator.
  Merging them tells an operator the wrong thing to do.
- **unavailable ≠ zero.** When the ontology side cannot be read, the two extra
  stages report `None`, never `0`. Zero reads as "checked, there are none".
- **pending is not mapped.** A confirmed crosswalk maps; a proposal does not.
"""

from __future__ import annotations

from src.bench import crosswalk as cw
from src.bench import source_funnel as sf


def cwrow(system: str, *, confidence=0.9, connectivity=None, confirmed=None) -> dict:
    row = {
        "external_key": "organization:acme",
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": system, "id": system},
    }
    if confidence is not None:
        row["confidence"] = confidence
    if connectivity is not None:
        row["connectivity"] = connectivity
    if confirmed is not None:
        row["confirmed"] = confirmed
    return row


def complete():
    return {s: {"ok": True, "evidence": f"p-{s}"} for s in sf.STATES}


# ------------------------------------------------------------ classification


def test_landed_without_mapping_is_counted_separately():
    out = sf.classify(landed_sources=["a", "b"], crosswalks=[])
    assert out["landed"] == 2
    assert out["mapped"] == 0
    assert out["landed_not_mapped"] == ["a", "b"]


def test_mapped_requires_a_confirmed_crosswalk():
    out = sf.classify(
        landed_sources=["a"], crosswalks=[cwrow("a", confidence=0.95)]
    )
    assert out["mapped"] == 1


def test_unconfirmed_crosswalk_does_not_map():
    """No confidence = nobody looked. It maps nothing, same as coverage."""
    out = sf.classify(landed_sources=["a"], crosswalks=[cwrow("a", confidence=None)])
    assert out["mapped"] == 0


def test_low_confidence_does_not_map():
    out = sf.classify(landed_sources=["a"], crosswalks=[cwrow("a", confidence=0.2)])
    assert out["mapped"] == 0


def test_evaluable_needs_all_three_states():
    out = sf.classify(
        landed_sources=["a"],
        crosswalks=[cwrow("a", connectivity={"catalog": {"ok": True, "evidence": "x"}})],
    )
    assert out["mapped"] == 1
    assert out["evaluable"] == 0


def test_complete_connectivity_is_evaluable():
    out = sf.classify(
        landed_sources=["a"], crosswalks=[cwrow("a", connectivity=complete())]
    )
    assert out["evaluable"] == 1


def test_mapped_but_not_landed_is_reported():
    """A mapping can exist before ingestion — that is a real, reportable state."""
    out = sf.classify(
        landed_sources=[], crosswalks=[cwrow("ghost", confidence=0.9)]
    )
    assert out["mapped_not_landed"] == ["ghost"]


def test_row_without_a_system_maps_nothing():
    out = sf.classify(
        landed_sources=["a"],
        crosswalks=[{"external_key": "x", "peer": {"kind": "ontology"}}],
    )
    assert out["mapped"] == 0


# ------------------------------------------------------------ stage_counts


def test_unavailable_ontology_reports_none_not_zero():
    base = {s: 3 for s in sf.PIPELINE_STAGES}
    out = sf.stage_counts(base, None)
    assert out["mapped"] is None
    assert out["evaluable"] is None
    assert out["ontology_available"] is False
    assert out["landed"] == 3, "crawler-side stages are unaffected"


def test_available_ontology_merges_counts():
    base = {s: 1 for s in sf.PIPELINE_STAGES}
    out = sf.stage_counts(base, {"mapped": 4, "evaluable": 2,
                                 "mapped_not_landed": [], "landed_not_mapped": []})
    assert out["mapped"] == 4 and out["evaluable"] == 2
    assert out["ontology_available"] is True


def test_stage_names_match_the_existing_funnel():
    """The panel already renders these seven names; renaming breaks its view."""
    assert sf.PIPELINE_STAGES == (
        "discoveries", "candidates", "analyses", "generated",
        "pending", "approved", "landed",
    )
    assert sf.ONTOLOGY_STAGES == ("mapped", "evaluable")


# --------------------------------------------- agreement with the seam's rule


def test_confirmation_rule_matches_the_seam():
    """This module restates `crosswalk.is_confirmed` because the crawler side
    cannot import the bench package. The restatement must not drift."""
    cases = [
        {"confidence": 0.95}, {"confidence": 0.2}, {}, {"confidence": None},
    ]
    for row in cases:
        mine = sf._is_confirmed(row)
        theirs = cw.is_confirmed(row, threshold=0.8)
        assert mine == theirs, f"drifted on {row}"


def test_source_catalog_peer_maps_by_id_not_system():
    """The scouting import writes `peer.system = "source_catalog"` (fixed) and the
    real source name in `peer.id`.

    Reading `system` compared the literal string "source_catalog" against
    crawl_sources rows, so a confirmed crosswalk never counted as mapped.
    Found on a real chain 2026-11-19: confirmation succeeded, `mapped` stayed 0.
    (The confidence here is above the review floor on purpose — the id-vs-system
    bug is what this pins; the machine-declaration floor is pinned separately.)
    """
    row = {
        "external_key": "organization:guangdong",
        "relation": "maps_to",
        "confidence": 0.9,
        "peer": {"kind": "external_id", "system": "source_catalog", "id": "广东统计局"},
    }
    out = sf.classify(landed_sources=["广东统计局"], crosswalks=[row])
    assert out["mapped"] == 1
    assert out["landed_not_mapped"] == []


def test_explicit_source_attribute_wins():
    row = {"source": "real-src", "confidence": 0.9,
           "peer": {"system": "source_catalog", "id": "other"}}
    out = sf.classify(landed_sources=["real-src"], crosswalks=[row])
    assert out["mapped"] == 1
