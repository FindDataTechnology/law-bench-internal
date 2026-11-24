"""Domain-face tools: 知验台's own model (domains / knowledge units / proposals).

This module is the reason the MCP server exists. Everything else in this
package serves a business line; this serves the platform.

Three rules that shape every function here:

1. **``domain`` is a required first argument.** There is no "current domain" and
   no default. Isolation is therefore a property of the query — `namespace =
   domain` — not of a prompt telling the model to behave. A tool that could be
   called without a domain would be a tool that can read across domains.

2. **Unknown and inaccessible are different answers.** A domain the caller
   cannot see raises rather than returning an empty list: an empty list reads
   as "this domain has nothing", which is a lie with consequences (someone
   concludes the corpus is missing).

3. **Read-only.** Promotion, publication and proposal confirmation stay on the
   workbench pages, where the session identity and the hard-stop list live.
   A machine caller has no session identity to stamp a review with.

Every function is a thin shell over ``src.bench.*``; the logic is the kernel's.
"""

from __future__ import annotations

from typing import Any, Optional

from ..annotations import annotations_for
from ..server import mcp


def _kernel():
    """Import the platform kernel lazily.

    The kernel pulls psycopg and the whole ``src.bench`` tree; importing it at
    module import time would make every MCP start pay for it even when the
    caller only wants the legal pack.
    """
    from src.bench import next_actions, proposals, store, unit_checks, workspaces

    return {
        "next_actions": next_actions,
        "proposals": proposals,
        "store": store,
        "unit_checks": unit_checks,
        "workspaces": workspaces,
    }


def _resolve_domain(conn: Any, domain: str) -> dict:
    """The domain row, or ``ValueError`` — never a silent empty result."""
    k = _kernel()
    if not domain:
        raise ValueError(
            "domain is required: the assistant works inside one domain at a time"
        )
    row = k["workspaces"].get_domain(conn, domain_key=domain)
    if row is None:
        raise ValueError(f"unknown domain {domain!r}")
    return row


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_list"))
async def domain_list(user_id: Optional[str] = None) -> list[dict]:
    """List the domains a person can work in.

    Parameters:
        user_id: the platform identity (email, or the IdP's subject id). When
            omitted, every non-archived domain is returned — that is the
            administrative view, not a personal one.

    Returns one entry per domain: key, name, path (the namespace), parent, and
    the caller's role in it when ``user_id`` is given.
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        rows = k["workspaces"].list_domains(conn, user_id=user_id)
        out = []
        for row in rows:
            entry = {
                "key": row["key"],
                "name": row.get("name"),
                "path": row.get("path") or row["key"],
                "parent_key": row.get("parent_key"),
            }
            if user_id:
                entry["role"] = k["workspaces"].get_active_role(
                    conn, domain_id=row["id"], user_id=user_id
                )
            out.append(entry)
        return out
    finally:
        conn.close()


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_context"))
async def domain_context(domain: str) -> dict:
    """What this domain's own console would tell you right now.

    Brief fields are built from the **same kernel functions the pages call**
    (``next_actions.for_domain`` for "what should happen next", ``unit_checks``
    for "what the machine already checked"). Recomputing them here would let the
    assistant contradict the page the operator is looking at.

    Parameters:
        domain: the domain key (the namespace holds the same value).
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        row = _resolve_domain(conn, domain)
        brief: dict = {"domain": domain, "name": row.get("name")}

        try:
            actions = k["next_actions"].for_domain(conn, row)
            top = (actions.get("ranked") or {}).get("top") or []
            brief["next_actions"] = [
                {"action": a.get("action"), "reason": a.get("reason"),
                 "entry": a.get("entry"), "priority": a.get("priority_key")}
                for a in top
            ]
            brief["next_actions_more"] = (actions.get("ranked") or {}).get("more", 0)
        except Exception as exc:  # noqa: BLE001 - a brief never fails the call
            brief["next_actions_error"] = f"{type(exc).__name__}: {exc}"

        # Kinds are discovered from the data, not hard-coded: a pack declares
        # them, and this server must not carry a list that goes stale.
        counts: dict[str, int] = {}
        rows = conn.execute(
            "SELECT kind, count(*) AS n FROM knowledge_units "
            "WHERE namespace = %s AND COALESCE(tags->>'deleted','false') <> 'true' "
            "GROUP BY kind ORDER BY kind",
            (domain,),
        ).fetchall()
        for r in rows:
            counts[(r["kind"] if isinstance(r, dict) else r[0])] = (
                r["n"] if isinstance(r, dict) else r[1]
            )
        brief["unit_counts_by_kind"] = counts
        brief["unit_total"] = sum(counts.values())

        try:
            brief["pending_proposals"] = k["proposals"].count_pending(
                conn, domain_key=domain
            )
        except Exception as exc:  # noqa: BLE001
            brief["pending_proposals_error"] = f"{type(exc).__name__}: {exc}"

        return brief
    finally:
        conn.close()


@mcp.tool(tags={"units"}, annotations=annotations_for("domain_units"))
async def domain_units(
    domain: str,
    kind: Optional[str] = None,
    query: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List this domain's knowledge units.

    Parameters:
        domain: the domain key — units live in the namespace of the same name.
        kind: restrict to one unit kind (``clause`` / ``law`` / ``concept`` /
            ``defines`` …). Kinds are declared by the domain's pack; asking for
            a kind that has no units returns ``[]`` rather than an error.
        query: substring over the external key or the body.
        include_deleted: include soft-deleted units (tombstones). Default false:
            a tombstone is not material anyone can use.
        limit: page size, default 50, hard ceiling 500.

    Returns external_key, kind, tier, and a truncated body preview per unit.
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        _resolve_domain(conn, domain)
        rows = k["store"].list_knowledge_units(
            conn,
            kind=kind,
            namespace=domain,
            query=query,
            include_deleted=include_deleted,
            limit=max(1, min(int(limit), 500)),
        )
        return [
            {
                "external_key": u["external_key"],
                "kind": u["kind"],
                "tier": u["tier"],
                "preview": (u.get("body") or "")[:200],
                "updated_at": u.get("updated_at"),
            }
            for u in rows
        ]
    finally:
        conn.close()


@mcp.tool(tags={"units"}, annotations=annotations_for("domain_unit_checks"))
async def domain_unit_checks(domain: str, kind: str, external_key: str) -> dict:
    """The machine verdicts on one unit, computed against its current body.

    Deterministic checkers registered for the unit's kind (a domain's pack ships
    them) answer what is mechanically checkable — is the text intact, does the
    article number agree with the stored locator, can it be traced to a source.
    Whether the content is *correct* is not the machine's call and is not
    answered here.

    Parameters:
        domain: the domain key.
        kind: the unit's kind.
        external_key: the unit's key inside the domain.

    Returns ``{checkable, passed, total, all_pass, failed_names, checks}``. When
    the kind has no registered checker, ``checkable`` is false — that is
    "nothing is mechanically checkable here", never "all checks passed".
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        _resolve_domain(conn, domain)
        unit = k["store"].get_knowledge_unit(
            conn, kind=kind, external_key=external_key, namespace=domain
        )
        if unit is None:
            raise ValueError(
                f"no {kind} unit {domain!r}/{external_key!r} in this domain"
            )
        checks = k["unit_checks"].checks_for_unit(unit)
        summary = k["unit_checks"].summarise(checks)
        return {**summary, "checks": checks}
    finally:
        conn.close()


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_proposals"))
async def domain_proposals(
    domain: str, state: Optional[str] = None, limit: int = 50
) -> list[dict]:
    """This domain's proposal inbox — drafts awaiting a human decision.

    Parameters:
        domain: the domain key.
        state: ``pending`` / ``confirmed`` / ``rejected``; omitted lists all.
        limit: page size, default 50.

    Confirming or rejecting a proposal is a human action on the workbench page
    (it carries the separation-of-duties rule); nothing here writes.
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        _resolve_domain(conn, domain)
        rows = k["proposals"].list_proposals(
            conn, domain_key=domain, state=state, limit=max(1, min(int(limit), 500))
        )
        return [
            {
                "id": p.get("id"),
                "kind": p.get("kind"),
                "external_key": p.get("external_key"),
                "state": p.get("state"),
                "submitted_by": p.get("submitted_by"),
                "submitted_at": p.get("submitted_at"),
            }
            for p in rows
        ]
    finally:
        conn.close()


@mcp.tool(tags={"domain"}, annotations=annotations_for("domain_proposal_get"))
async def domain_proposal_get(domain: str, proposal_id: int) -> dict:
    """One proposal in full, plus its event trail.

    Parameters:
        domain: the domain key.
        proposal_id: the proposal's id inside this domain.
    """
    from src.eval.db import connect

    k = _kernel()
    conn = connect()
    try:
        _resolve_domain(conn, domain)
        proposal = k["proposals"].get(conn, domain_key=domain, proposal_id=proposal_id)
        if proposal is None:
            raise ValueError(f"no proposal {proposal_id} in domain {domain!r}")
        events = k["proposals"].events_for(conn, proposal_id=proposal_id)
        return {"proposal": proposal, "events": events}
    finally:
        conn.close()