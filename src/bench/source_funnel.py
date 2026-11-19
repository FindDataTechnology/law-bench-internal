"""Pipeline stages that live on the ontology side, not in the crawler database.

The discovery funnel already counts seven stages in the crawler panel
(`fd-open-data-mcp`'s `discovery_funnel`): discoveries → candidates → analyses →
generated → pending → approved → landed. Two more stages exist, but they answer
questions the crawler database cannot:

    landed     — the crawler unit exists in `crawl_sources` (pipeline fact)
    mapped     — the source has a confirmed crosswalk (ontology fact)
    evaluable  — that crosswalk's three-state evidence is complete

**They must not be merged into one "landed" number.** "We ingested it" and "we
know which part of the ontology it fills" are different states with different
remedies: the first needs an engineer, the second needs a curator.

Why this module rather than editing the panel: the two facts live in different
databases (crawler vs platform) and the panel's contract is that each partial
degrades independently. Reading the ontology through a second connection from
the crawler panel would couple two deployments' availability. Here the counts
are a pure function of the rows handed in, so whoever can read both sides joins
them — and the join is testable without either database.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: The crawler-side stages, in order. Kept here so both sides agree on the names
#: the funnel has always used (changing them would break the panel's own view).
PIPELINE_STAGES = (
    "discoveries",
    "candidates",
    "analyses",
    "generated",
    "pending",
    "approved",
    "landed",
)

#: The two ontology-side stages this module adds.
ONTOLOGY_STAGES = ("mapped", "evaluable")


def classify(
    *,
    landed_sources: Iterable[str],
    crosswalks: Iterable[dict],
    confirmed_only: bool = True,
) -> dict:
    """Split sources into (landed, mapped, evaluable).

    ``landed_sources`` is the crawler-side set (`crawl_sources.source`).
    ``crosswalks`` are ontology rows, each carrying at least
    ``external_key`` / ``relation`` / ``peer`` and optionally ``confidence`` and
    ``connectivity``.

    A source counts as **mapped** when it has at least one confirmed crosswalk —
    a pending or rejected proposal is not a mapping, exactly as a pending
    proposal never contributes to coverage.

    A source counts as **evaluable** when that crosswalk's connectivity has all
    three states cleared. An unprobed source can be mapped but not evaluable;
    that distinction is the point of the third stage.
    """
    landed = set(landed_sources)

    # peer.system carries the source identity for crosswalks written by the
    # source-scouting import. Rows that name no source are not attributable and
    # therefore map nothing.
    mapped_systems: set[str] = set()
    evaluable_systems: set[str] = set()

    for row in crosswalks:
        peer = (row or {}).get("peer") or {}
        system = peer.get("system") if isinstance(peer, dict) else None
        if not system:
            continue
        if confirmed_only and not _is_confirmed(row):
            continue
        mapped_systems.add(system)
        if _connectivity_complete((row or {}).get("connectivity")):
            evaluable_systems.add(system)

    return {
        "landed": len(landed),
        "mapped": len(landed & mapped_systems),
        "evaluable": len(landed & evaluable_systems),
        # A source can be mapped by a crosswalk that was created before it was
        # ingested, or ingested without any mapping — both are real states.
        "mapped_not_landed": sorted(mapped_systems - landed),
        "landed_not_mapped": sorted(landed - mapped_systems),
    }


def stage_counts(base: dict, ontology: Optional[dict]) -> dict:
    """Merge the crawler-side counts with the ontology-side classification.

    ``ontology=None`` means the ontology side could not be read. The two extra
    stages are then reported as ``None`` — **not 0**. Zero reads as "we checked
    and there are none", which is the opposite of "we could not check".
    """
    out = {stage: base.get(stage) for stage in PIPELINE_STAGES}
    if ontology is None:
        out["mapped"] = None
        out["evaluable"] = None
        out["ontology_available"] = False
        return out
    out["mapped"] = ontology.get("mapped")
    out["evaluable"] = ontology.get("evaluable")
    out["mapped_not_landed"] = ontology.get("mapped_not_landed", [])
    out["landed_not_mapped"] = ontology.get("landed_not_mapped", [])
    out["ontology_available"] = True
    return out


STATES = ("catalog", "executor_tests", "live")


def _connectivity_complete(connectivity: Any) -> bool:
    if not isinstance(connectivity, dict):
        return False
    for state in STATES:
        value = connectivity.get(state)
        if not isinstance(value, dict) or value.get("ok") is not True:
            return False
        if not value.get("evidence"):
            return False
    return True


def _is_confirmed(row: dict) -> bool:
    """A crosswalk is confirmed when it carries a confidence at or above the
    review floor, or when the caller marked it explicitly.

    Mirrors `crosswalk.is_confirmed`'s fail-closed rule: no confidence means
    nobody has looked, so it maps nothing. Duplicating the predicate here would
    be a second definition — this module is imported where the bench package is
    not on the path (the crawler side), which is why it states the rule locally
    and pins it with a test against the original.
    """
    if row.get("confirmed") is True:
        return True
    confidence = row.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return False
    return float(confidence) >= 0.8
