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
    role = workspaces.get_active_role(conn, domain_id=domain["id"], user_id=user.sub)
    if role is None:
        return None
    return domain_key, role


#: Injected by the proxy, never trusted from the client.
_SCOPE_HEADERS = ("x-lawbench-domain", "x-lawbench-role")


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
