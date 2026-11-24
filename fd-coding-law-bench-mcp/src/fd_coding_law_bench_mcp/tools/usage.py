"""Assistant usage metering — who spent how much, in which domain.

Why this exists: the assistant has no metering at all. Every other machine
surface here has a ledger (`domain_agent_runs`), but the assistant is a person
driving a model through a chat panel, and once it opened up from admin-only to
every domain member the token spend went from zero to real. Without a record
there is no way to answer "which domain is burning budget" or to put a cap
anywhere.

Why a separate table and not `domain_agent_runs`: that ledger's `open` refuses
any identity that is not an agent (`agent_ids.is_agent`), because a human's
trail belongs in `authoring_events`. An assistant turn is a person using a
machine — folding it into the agent ledger would make "who did this turn"
unanswerable.

What this does NOT do: enforce a budget. It records; a cap needs a decision about
whose budget it is (per user? per domain? per tenant?) that nobody has made. A
meter with no cap is still worth having — it turns "we don't know" into "here is
the number".
"""

from __future__ import annotations

from typing import Optional

from ..annotations import annotations_for
from ..server import mcp


@mcp.tool(tags={"metrics"}, annotations=annotations_for("assistant_usage_record"))
async def assistant_usage_record(
    domain: str,
    actor: str,
    role: Optional[str] = None,
    model: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
    outcome: str = "ok",
) -> dict:
    """Record one assistant turn.

    Called by the runtime after a run settles. Every count is optional: a run
    that failed before the model answered has no token counts, and recording it
    with NULLs is more honest than dropping it (a missing row and a zero-cost
    row are different facts).

    Parameters:
        domain: the domain the turn happened in.
        actor: the person's identity (the session's `sub`).
        role: their role in that domain, for per-role breakdowns.
        model: the model that answered.
        tokens_in / tokens_out: token counts, when the provider reported them.
        elapsed_ms: wall time of the whole run.
        outcome: ``ok`` / ``error`` / ``aborted``.
    """
    from src.eval.db import connect

    if not domain:
        raise ValueError("domain is required")
    if not actor:
        raise ValueError("actor is required: an unattributed turn is not a record")
    if outcome not in ("ok", "error", "aborted"):
        raise ValueError(f"unknown outcome {outcome!r}")

    conn = connect()
    try:
        row = conn.execute(
            "INSERT INTO domain_assistant_turns "
            "(domain_key, actor, role, model, tokens_in, tokens_out, elapsed_ms, outcome) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (domain, actor, role, model, tokens_in, tokens_out, elapsed_ms, outcome),
        ).fetchone()
        conn.commit()
        return {"id": (row["id"] if isinstance(row, dict) else row[0])}
    finally:
        conn.close()


@mcp.tool(tags={"metrics"}, annotations=annotations_for("assistant_usage_summary"))
async def assistant_usage_summary(domain: str, days: int = 7) -> dict:
    """Assistant spend in one domain over the last ``days`` days.

    Returns totals plus a per-actor breakdown, because the useful question is
    never "how much did this domain cost" alone — it is "and who".

    Parameters:
        domain: the domain key.
        days: lookback window, default 7, clamped to [1, 365].
    """
    from src.eval.db import connect
    from src.bench import workspaces

    conn = connect()
    try:
        if workspaces.get_domain(conn, domain_key=domain) is None:
            raise ValueError(f"unknown domain {domain!r}")
        window = max(1, min(int(days), 365))
        rows = conn.execute(
            "SELECT actor, count(*) AS turns, "
            "       coalesce(sum(tokens_in),0) AS tokens_in, "
            "       coalesce(sum(tokens_out),0) AS tokens_out, "
            "       coalesce(sum(elapsed_ms),0) AS elapsed_ms, "
            "       count(*) FILTER (WHERE outcome <> 'ok') AS failed "
            "FROM domain_assistant_turns "
            "WHERE domain_key = %s AND created_at > now() - interval '%s days' "
            "GROUP BY actor ORDER BY (coalesce(sum(tokens_in),0) + coalesce(sum(tokens_out),0)) DESC",
            (domain, window),
        ).fetchall()
        by_actor = [
            {
                "actor": (r["actor"] if isinstance(r, dict) else r[0]),
                "turns": (r["turns"] if isinstance(r, dict) else r[1]),
                "tokens_in": int(r["tokens_in"] if isinstance(r, dict) else r[2]),
                "tokens_out": int(r["tokens_out"] if isinstance(r, dict) else r[3]),
                "elapsed_ms": int(r["elapsed_ms"] if isinstance(r, dict) else r[4]),
                "failed": (r["failed"] if isinstance(r, dict) else r[5]),
            }
            for r in rows
        ]
        return {
            "domain": domain,
            "days": window,
            "turns": sum(a["turns"] for a in by_actor),
            "tokens_in": sum(a["tokens_in"] for a in by_actor),
            "tokens_out": sum(a["tokens_out"] for a in by_actor),
            "by_actor": by_actor,
        }
    finally:
        conn.close()