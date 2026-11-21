#!/usr/bin/env python3
"""Reject proposals that can never land, with a reviewable operator identity.

    uv run python scripts/reject_unlandable_proposals.py --domain data-ontology \\
        --operator chengsishi --reason duplicate-submissions --dry-run
    uv run python scripts/reject_unlandable_proposals.py --domain data-ontology \\
        --operator chengsishi --reason duplicate-submissions --execute

**Why a script and not a psql UPDATE.** Rejection writes ``decided_by``, ends the
claim, and makes the same evidence un-submittable again — it is a decision, not
a cleanup. Doing it as SQL would skip the event trail and the machine-identity
gate, and the audit would show a state change with no actor.

**Why the operator is spelled out.** The domain this was written for
(``data-ontology``) has no human member at all: it is owned by
``system:ontology-fleet`` and its only member is ``fleet:ontology-builder``.
Until 2026-11-21 the way out of that was any ``system:*`` string, i.e. permission
decided by string shape. The ``ops:<operator>/<reason>`` class replaces it with
an identity that names both the person and the ground for the decision.

**What it refuses.** Proposals are only rejected when the script can *show* they
cannot land or are duplicates. It does not take "these look wrong" as a reason:

- ``unlandable-evidence``: the proposal's evidence is not the shape its lane
  needs (a relationship needs a dict carrying ``from_key``/``to_key``; these
  carried a JSON string holding a list), so confirmation would fail every time.
- ``duplicate-claim``: another pending or confirmed proposal in the same domain
  asserts the same thing under a different key (typically an ``entity:`` prefix
  that key folding does not strip).

Anything else is reported and left alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: Relationship lane kinds: their confirmation reads endpoints out of the
#: evidence dict, so a payload that is not such a dict can never land.
RELATIONSHIP_KINDS = frozenset({"n:1", "1:n", "m:n", "has_field", "references"})


def _evidence_is_dict(evidence) -> bool:
    return isinstance(evidence, dict)


def classify(proposal: dict) -> str | None:
    """Why this proposal cannot stand, or ``None`` when it is not ours to judge.

    Returns one of the reason slugs the script refuses to run without.
    """
    kind = (proposal.get("kind") or "").strip()
    evidence = proposal.get("evidence")

    # A relationship is confirmed via `_relationship_endpoints`, which requires a
    # dict carrying from_key/to_key. Evidence stored as a string (even a string
    # of JSON) can never satisfy it, so the proposal occupies a review slot
    # forever. This is a structural fact about the stored payload, not a
    # judgement about the mapping.
    if kind in RELATIONSHIP_KINDS:
        if not _evidence_is_dict(evidence):
            return "unlandable-evidence"
        if not (evidence.get("from_key") or evidence.get("from")):
            return "unlandable-evidence"
        return None

    key = (proposal.get("external_key") or "").strip()
    # An `entity:` prefix is not stripped by key folding, so this row would become
    # a *second* knowledge unit for the same dataset rather than the same one.
    if key.startswith("entity:"):
        return "duplicate-claim"
    return None


def _claim_of(proposal: dict) -> tuple[str, str, tuple[str, ...]] | None:
    """What this proposal actually asserts: (kind, dataset, key columns).

    Duplicate detection must key on the **claim**, not just the dataset. Measured
    2026-11-21: `#88` asserts a three-column key `(code,item,period)` while `#91`
    asserts two `(code,item)` for the same dataset. Those are different claims
    about the same data — collapsing them would throw away whichever one the
    reader has not seen yet.

    Key columns are read from the evidence's `columns` (the columns the submitter
    measured), falling back to "unspecified" so two proposals that name no key
    columns still compare equal to each other rather than to everything.
    """
    dataset = _dataset_of(proposal)
    if dataset is None:
        return None
    evidence = proposal.get("evidence")
    columns: tuple[str, ...] = ()
    entries = evidence if isinstance(evidence, list) else [evidence]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("columns")
        if isinstance(raw, list) and raw:
            columns = tuple(str(c).strip() for c in raw)
            break
    return (proposal.get("kind") or "", dataset, columns)


def _dataset_of(proposal: dict) -> str | None:
    """The dataset a proposal is about, from its evidence payload.

    This is the identity duplicates collide on, and it is deliberately read from
    the evidence rather than the key: the whole problem is that two submissions
    used *different keys* for one dataset.

    `list_proposals` returns the evidence already decoded (dict or list), so both
    shapes are handled directly; a bare string is still parsed because the
    confirmation path stores exactly what it was given.
    """
    evidence = proposal.get("evidence")
    if isinstance(evidence, dict):
        for field in ("dataset", "dataset_key"):
            value = evidence.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if isinstance(evidence, list):
        for entry in evidence:
            if isinstance(entry, dict):
                value = entry.get("dataset") or entry.get("dataset_key")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None
    if isinstance(evidence, str):
        try:
            return _dataset_of({"evidence": json.loads(evidence)})
        except (TypeError, ValueError):
            return None
    return None


def _evidence_weight(proposal: dict) -> int:
    """How much verifiable content the evidence carries, as a tie-breaker.

    Not a score of correctness — just "which of these two submissions actually
    measured something". The richer one is kept for a human to judge; the thinner
    one is a duplicate of the same claim and is what gets rejected.
    """
    evidence = proposal.get("evidence")
    if isinstance(evidence, (dict, list)):
        return len(json.dumps(evidence, ensure_ascii=False))
    return len(evidence or "")


def collapse_duplicates(proposals: list[dict]) -> tuple[list[dict], dict[int, str]]:
    """Pick, per identical **claim**, the submission to keep; mark the rest.

    Grouping is by `_claim_of` — kind + dataset + the key columns the submitter
    measured. Two submissions of one claim under different keys are not
    corroboration: confirming both would write two knowledge units for one
    dataset. Two submissions making *different* claims about the same dataset are
    not duplicates and are left for a human.

    The keeper is the submission with the most evidence; ties keep the lowest id
    so the outcome does not depend on query order.
    """
    groups: dict[tuple, list[dict]] = {}
    for proposal in proposals:
        claim = _claim_of(proposal)
        if claim is None:
            continue
        groups.setdefault(claim, []).append(proposal)

    keep: dict[int, str] = {}
    for claim, members in groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda p: (-_evidence_weight(p), p["id"]))
        keep[ordered[0]["id"]] = "kept"
        for other in ordered[1:]:
            keep[other["id"]] = "duplicate-claim"
    return proposals, keep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--operator", required=True,
                        help="person making the operational decision")
    parser.add_argument("--reason", required=True,
                        help="short slug naming the ground (goes in the identity)")
    parser.add_argument("--only", type=int, action="append", default=None,
                        help="restrict to these proposal ids (repeatable)")
    parser.add_argument("--execute", action="store_true",
                        help="actually reject; without it this is a dry run")
    # Accepted as an explicit no-op so a dry run reads the same way as every other
    # script in this repo. `--execute` is what writes; neither flag means dry run,
    # which is the safe default for something that ends a claim permanently.
    parser.add_argument("--dry-run", action="store_true",
                        help="explicit no-op; dry run is the default anyway")
    args = parser.parse_args(argv)

    from src.bench import agent_ids, proposals, workspaces
    from src.eval.db import connect

    actor = agent_ids.ops_identity(args.operator, args.reason)
    if not agent_ids.is_ops(actor):  # defensive: the builder should guarantee it
        print(f"REFUSED: {actor!r} is not a well-formed ops identity", file=sys.stderr)
        return 1

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"domain {args.domain!r} not found", file=sys.stderr)
            return 1

        pending = proposals.list_proposals(
            conn, domain_key=args.domain, state="pending"
        )
        if args.only:
            want = set(args.only)
            pending = [p for p in pending if p["id"] in want]

        decidable = [(p, classify(p)) for p in pending]
        decidable = [(p, why) for p, why in decidable if why]

        # Same claim, two keys: keep the submission that actually measured
        # something and reject the thinner one. Done after the structural pass so
        # a duplicate of an unlandable row is still just "unlandable".
        decided_ids = {p["id"] for p, _ in decidable}
        survivors = [p for p in pending if p["id"] not in decided_ids]
        _, dupes = collapse_duplicates(survivors)
        for proposal in survivors:
            verdict = dupes.get(proposal["id"])
            if verdict == "duplicate-claim":
                decidable.append((proposal, "duplicate-claim"))
        decidable.sort(key=lambda pair: pair[0]["id"])

        print(f"domain {args.domain}: {len(pending)} pending, "
              f"{len(decidable)} decidable by this script's rules")
        for proposal, why in decidable:
            print(f"  #{proposal['id']:<4} {why:22s} {proposal['kind']:10s} "
                  f"{proposal['external_key']}")

        decided_ids = {p["id"] for p, _ in decidable}
        kept = [p for p in pending if p["id"] not in decided_ids]
        if kept:
            print(f"\n{len(kept)} left for a human (this script makes no call):")
            for proposal in kept:
                print(f"  #{proposal['id']:<4} {proposal['kind']:10s} "
                      f"{proposal['external_key']}")

        if not args.execute:
            print("\nDRY-RUN — nothing written. Pass --execute to reject.")
            return 0
        if not decidable:
            print("\nnothing to do")
            return 0

        done = 0
        for proposal, why in decidable:
            note = (
                f"运维裁决 {why}：{_note_for(why)}"
                f"（operator={args.operator}，依据见 scripts/reject_unlandable_proposals.py）"
            )
            proposals.reject(
                conn, domain_key=args.domain, proposal_id=proposal["id"],
                actor=actor, note=note,
            )
            done += 1
        print(f"\nrejected {done} proposal(s) as {actor}")

        remaining = proposals.count_pending(conn, domain_key=args.domain)
        print(f"pending left in {args.domain}: {remaining}")
        return 0
    finally:
        conn.close()


def _note_for(reason: str) -> str:
    return {
        "unlandable-evidence":
            "evidence 存为字符串而非对象，关系建议的确认路径要求对象且带 "
            "from_key/to_key，因此永远确认不了",
        "duplicate-claim":
            "external_key 带 entity: 前缀且归名规则不剥离，确认后会成为同一数据集的"
            "第二份知识单元；同一主张已有不带前缀的提交",
    }.get(reason, reason)


if __name__ == "__main__":
    raise SystemExit(main())
