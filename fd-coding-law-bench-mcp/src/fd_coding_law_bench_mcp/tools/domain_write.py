"""Domain-face write tools — the two actions a machine may legitimately take.

Why only two, and why these two:

The kernel already decided (2026-11-21, ``proposals.confirm``) that **the
authority to sign comes from the tier, not the shape of the identity**. A
machine that is an active ``lead`` of a domain may confirm a proposal; what it
produces is ``silver``, and promoting to ``gold`` still requires a human reviewer
stamp. That is the boundary this module implements:

- ``domain_proposal_confirm`` — allowed, but the caller must name a real
  identity that holds ``lead`` in the domain. The kernel re-checks the
  separation-of-duties rule (a producer cannot confirm its own proposal).
- ``domain_unit_promote`` — allowed one step at a time, and **to silver only**.
  ``gold`` is refused here on purpose: the kernel requires a reviewer identity
  for gold, and a machine has none to give. Silently stamping "machine" as the
  reviewer would fabricate an audit record.

Publication is not here at all: publishing freezes a version that consumers pull,
and no machine identity has been granted that.

Every tool takes ``actor`` explicitly. There is no ambient "current identity" for
a machine caller, and inventing one would be the same mistake as trusting a
client-supplied role.
"""

from __future__ import annotations

from typing import Optional

from ..annotations import annotations_for
from ..server import mcp


def _require_lead(conn, domain: str, actor: str) -> dict:
    """The domain row, or raise — the actor must be an active lead of it.

    ``actor`` is a claim from the caller, so it is checked against the
    membership table before anything is written. That check is the entire reason
    this function exists: without it, naming any string would sign as that
    person.
    """
    from src.bench import workspaces

    if not domain:
        raise ValueError("domain is required")
    if not actor or not actor.strip():
        raise ValueError("actor is required: sign-offs carry an identity")
    row = workspaces.get_domain(conn, domain_key=domain)
    if row is None:
        raise ValueError(f"unknown domain {domain!r}")
    role = workspaces.get_active_role(conn, domain_id=row["id"], user_id=actor)
    if role is None:
        raise PermissionError(
            f"{actor!r} has no active membership in domain {domain!r}"
        )
    if workspaces.ROLE_RANK.get(role, -1) < workspaces.ROLE_RANK["lead"]:
        raise PermissionError(
            f"{actor!r} is {role!r} in domain {domain!r}; confirming requires 'lead'"
        )
    return row


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_proposal_confirm"))
async def domain_proposal_confirm(
    domain: str, proposal_id: int, actor: str, note: str = ""
) -> dict:
    """Confirm one proposal into the ontology, on behalf of ``actor``.

    The kernel's rules still apply and are not bypassed here:
    - the caller's identity must hold ``lead`` in this domain (checked);
    - a producer cannot confirm their own proposal (the kernel refuses);
    - the confirmed output lands at tier ``silver`` — promoting to ``gold``
      needs a human reviewer and is not offered by this face.

    Parameters:
        domain: the domain key.
        proposal_id: the proposal's id inside this domain.
        actor: the identity signing. Must be an active ``lead`` member.
        note: free-text decision note, recorded in the event trail.
    """
    from src.eval.db import connect
    from src.bench import proposals

    conn = connect()
    try:
        _require_lead(conn, domain, actor)
        result = proposals.confirm(
            conn, domain_key=domain, proposal_id=proposal_id, actor=actor
        )
        if note and hasattr(proposals, "events_for"):
            # The kernel writes the decision; a caller-supplied note is appended
            # as an event so it is visible next to the decision it explains.
            try:
                conn.execute(
                    "INSERT INTO domain_proposal_events "
                    "(proposal_id, kind, actor, note, created_at) "
                    "VALUES (%s, 'note', %s, %s, now())",
                    (proposal_id, actor, note),
                )
                conn.commit()
            except Exception:  # noqa: BLE001 - a note never fails the decision
                pass
        return result
    finally:
        conn.close()


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_unit_promote"))
async def domain_unit_promote(
    domain: str, kind: str, external_key: str, actor: str
) -> dict:
    """Move one unit up **one** step of the ladder, on behalf of ``actor``.

    Only ``raw → silver`` (and ``bronze → silver``) is reachable here. ``gold``
    is refused deliberately: the kernel requires a reviewer identity for gold and
    a machine has none to give — writing "machine" as the reviewer would forge a
    human-verification stamp, which is exactly what the tier guards exist to
    prevent.

    Parameters:
        domain: the domain key.
        kind: the unit's kind.
        external_key: the unit's key inside the domain.
        actor: the identity performing the step. Must be an active ``lead``.
    """
    from src.eval.db import connect
    from src.bench import promotion

    conn = connect()
    try:
        _require_lead(conn, domain, actor)
        unit = promotion._get_unit(
            conn, kind=kind, external_key=external_key, namespace=domain
        )
        nxt = _next_tier(promotion, unit["tier"])
        if nxt is None:
            raise ValueError(f"unit is already at the top of the ladder ({unit['tier']})")
        if nxt == "gold":
            raise PermissionError(
                "promoting to gold requires a human reviewer identity; "
                "this face stops at silver"
            )
        return promotion.promote_unit(
            conn,
            kind=kind,
            external_key=external_key,
            namespace=domain,
            to_tier=nxt,
            reviewer=actor,
        )
    finally:
        conn.close()


def _next_tier(promotion, tier: str | None) -> Optional[str]:
    """One step up, or ``None`` at the top (same rule the console page uses)."""
    chain = promotion.CHAIN
    if tier == promotion.SYNC_TIER:
        return "silver"
    if tier not in chain:
        return None
    i = chain.index(tier)
    return chain[i + 1] if i + 1 < len(chain) else None