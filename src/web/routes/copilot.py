"""Admin-assistant chat proxy: ``/copilotkit`` -> the CopilotKit runtime.

The floating assistant's browser island talks to this same-origin route with
the workbench session cookie; this module is the ONLY public path to the
runtime (change ``add-admin-copilot-assistant``). The whole router is gated by
``require_scope("admin")`` — unauthenticated requests 401 and non-admin
sessions 403 before anything is forwarded, so the runtime itself can stay
ClusterIP-only behind no auth of its own.

Forwarding is streaming (``aiter_raw``), not buffered: CopilotKit speaks a
streaming GraphQL protocol and tool loops (e.g. ``compare_run``) can run for
minutes, so read/write timeouts are raised accordingly. Request cookies and
credentials are stripped — the runtime trusts nothing about the caller; the
scope check above is the entire gate.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from ..auth.deps import User, get_current_user
from ..deps import DbConn, get_db
from ...settings import COPILOT_RUNTIME_URL

#: Requests are admitted by the domain gate below, not by a platform scope.
#: `require_scope("admin")` used to gate the whole router and locked out every
#: domain member (change `scope-assistant-to-domain`).
router = APIRouter(tags=["assistant"])

# compare_run / contract generation over chat can legitimately run for many
# minutes; the proxy must not cut a live stream.
_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=900.0, pool=10.0)

# Connection-scoped headers must not cross the proxy boundary (RFC 9110 §7.6.1)
# plus the workbench's own credentials, which are meaningless to the runtime.
_DROPPED_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "cookie",
    "authorization",
    "x-api-key",
}
_DROPPED_RESPONSE_HEADERS = {
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
}


def _build_client() -> httpx.AsyncClient:
    """Factory so tests can swap in an ``httpx.MockTransport``-based client."""
    return httpx.AsyncClient(timeout=_TIMEOUT)


def _forward_headers(request: Request) -> dict[str, str]:
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _DROPPED_REQUEST_HEADERS
    }


def _response_headers(upstream: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() not in _DROPPED_RESPONSE_HEADERS
    }


async def _cleanup(upstream: httpx.Response, client: httpx.AsyncClient) -> None:
    await upstream.aclose()
    await client.aclose()


def _resolve_scope(request: Request, user: User, conn: DbConn) -> tuple[str, str] | None:
    """``(domain_key, role)`` for this request, or ``None`` when it has none.

    The domain comes from the **request**, never from a remembered value: the
    island sends it (``X-Lawbench-Domain``), and this function re-checks that the
    caller really is an active member of it. A client-supplied domain is a
    claim, not a fact — the membership lookup is what makes it true.

    ``None`` means "deny", and the caller must not degrade into a domain-less
    assistant (design D4).
    """
    from ...bench import workspaces

    domain_key = (request.headers.get("x-lawbench-domain") or "").strip()
    if not domain_key:
        return None
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        return None
    # Same dual-identifier rule as the chrome's resolver: membership rows may
    # carry either the Logto sub or the email (production has both shapes).
    for candidate in (user.sub, getattr(user, "email", "") or ""):
        if not candidate:
            continue
        role = workspaces.get_active_role(
            conn, domain_id=domain["id"], user_id=candidate
        )
        if role is not None:
            return domain_key, role
    return None


#: Injected by the proxy, never trusted from the client.
_SCOPE_HEADERS = ("x-lawbench-domain", "x-lawbench-role", "x-lawbench-context")


def _domain_context(conn, domain: dict) -> str:
    """A one-line factual brief about the domain, for the model's system prompt.

    Deliberately built from the SAME modules the pages use — ``next_actions`` for
    "what should happen next" and ``unit_checks`` for "what the machine already
    checked". If this recomputed either, the assistant could tell the operator
    something the page in front of them contradicts (design D3).

    Every failure degrades to omitting that clause, never to a made-up one: an
    assistant that invents "3 items failed the checks" is worse than one that
    says nothing about checks.
    """
    bits: list[str] = []
    try:
        from ...bench import next_actions

        result = next_actions.for_domain(conn, domain)
        top = (result.get("ranked") or {}).get("top") or []
        if top:
            first = top[0]
            reason = first.get("reason") or ""
            action = first.get("action") or ""
            if reason and action:
                bits.append(f"下一动作：{action}（理由：{reason}）")
        else:
            bits.append("本域当前没有待办动作")
    except Exception:  # noqa: BLE001 - context is advisory, never load-bearing
        pass
    try:
        from ...bench import data_checks, unit_checks
        from ...bench.store import list_knowledge_units

        namespace = domain.get("path") or domain.get("key")
        totals = {"checkable": 0, "failed": 0, "uncheckable_kinds": set()}
        for kind in data_checks._CHECKERS:  # kinds with a checker registered
            units = list_knowledge_units(
                conn, kind=kind, namespace=namespace, limit=200
            )
            for u in units:
                s = unit_checks.summarise(unit_checks.checks_for_unit(u))
                if not s["checkable"]:
                    continue
                totals["checkable"] += 1
                if not s["all_pass"]:
                    totals["failed"] += 1
        if totals["checkable"]:
            bits.append(
                f"机器核对：已判 {totals['checkable']} 条，其中 {totals['failed']} 条有未通过项"
            )
        else:
            bits.append("机器核对：本域还没有可机械核对的单位")
    except Exception:  # noqa: BLE001
        pass
    return "；".join(bits)


@router.api_route(
    "/copilotkit",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    response_model=None,
)
@router.api_route(
    "/copilotkit/{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    response_model=None,
)
async def copilot_proxy(
    request: Request,
    user: User = Depends(get_current_user),
    conn: DbConn = Depends(get_db),
    rest: str = "",
) -> StreamingResponse | JSONResponse:
    """Stream the request to the runtime and its response back, unbuffered.

    Admission is the domain gate: the caller must be an active member of the
    domain the island says it is in. Anonymous callers 401 upstream of here
    (``get_current_user``); a signed-in caller with no resolvable domain gets a
    distinguishable 403 and the runtime is never reached.
    """
    if not COPILOT_RUNTIME_URL:
        return JSONResponse(
            status_code=503,
            content={"error": "assistant runtime not configured (COPILOT_RUNTIME_URL unset)"},
        )
    scope = _resolve_scope(request, user, conn)
    if scope is None:
        # Distinguishable on purpose: "you have no domain here" is a different
        # fact from "you are not signed in", and only one of them is fixed by
        # joining a domain.
        return JSONResponse(
            status_code=403,
            content={"error": "no_domain_context",
                     "detail": "this assistant works inside a domain; "
                               "you have no active membership in the requested one"},
        )
    domain_key, role = scope
    target = f"{COPILOT_RUNTIME_URL}/copilotkit"
    if rest:
        target = f"{target}/{rest}"

    headers = _forward_headers(request)
    # Drop any client-supplied scope headers, then set the verified pair.
    for name in list(headers):
        if name.lower() in _SCOPE_HEADERS:
            del headers[name]
    headers["X-Lawbench-Domain"] = domain_key
    headers["X-Lawbench-Role"] = role
    # ASCII-safe transport: the brief is Chinese, and an HTTP header cannot carry
    # raw non-ASCII. Base64 keeps the proxy contract simple (one header) and the
    # runtime decodes it back before injecting.
    try:
        from ...bench import workspaces

        domain_row = workspaces.get_domain(conn, domain_key=domain_key)
        brief = _domain_context(conn, domain_row) if domain_row else ""
    except Exception:  # noqa: BLE001 - a brief is advisory; never block the chat
        brief = ""
    if brief:
        import base64

        headers["X-Lawbench-Context"] = base64.b64encode(
            brief.encode("utf-8")
        ).decode("ascii")

    client = _build_client()
    upstream_request = client.build_request(
        request.method,
        target,
        headers=headers,
        content=await request.body(),
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"error": f"assistant runtime unreachable: {exc}"},
        )
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=_response_headers(upstream),
        background=BackgroundTask(_cleanup, upstream, client),
    )
