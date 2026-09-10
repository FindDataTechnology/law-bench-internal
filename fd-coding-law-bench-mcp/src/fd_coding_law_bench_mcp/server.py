"""The single FastMCP server instance + tool registration.

The tool modules are imported at the bottom (after ``mcp`` is defined) so each
can do ``from ..server import mcp`` and register its ``@mcp.tool`` decorators.
``src.*`` imports are deferred to call time inside each tool, keeping server
startup light and avoiding import-time coupling to DB / network backends.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

mcp: FastMCP = FastMCP("law-bench")

# Importing the tool modules registers their @mcp.tool decorators. Order does
# not matter; the names are re-exported for callers / tests that want them.
from .tools import compare as _compare  # noqa: E402,F401
from .tools import clauses as _clauses  # noqa: E402,F401
from .tools import evaluate as _evaluate  # noqa: E402,F401
from .tools import generate as _generate  # noqa: E402,F401
from .tools import law_info as _law_info  # noqa: E402,F401
from .tools import pipeline as _pipeline  # noqa: E402,F401
from .tools import auto_pipeline as _auto_pipeline  # noqa: E402,F401
from .tools import tag_iteration as _tag_iteration  # noqa: E402,F401
from .tools import prompts as _prompts  # noqa: E402,F401
from .tools import rag as _rag  # noqa: E402,F401
from .tools import rubrics as _rubrics  # noqa: E402,F401
from .tools import tags as _tags  # noqa: E402,F401
from .tools import content as _content  # noqa: E402,F401
from .tools import batch as _batch  # noqa: E402,F401
from .tools import catalog as _catalog  # noqa: E402,F401
from .tools import artifacts as _artifacts  # noqa: E402,F401
from .tools import agent_metrics as _agent_metrics  # noqa: E402,F401
from .tools import validation as _validation  # noqa: E402,F401


def _extract_access_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Pull the shared token from ``Authorization: Bearer`` or ``X-API-Key``.

    Direct MCP clients authenticate with the standard bearer header; the AI
    Gateway's ``api_key`` backend scheme forwards the credential as
    ``X-API-Key``, so both must be accepted.
    """
    bearer: str | None = None
    api_key: str | None = None
    for name, value in headers:
        lowered = name.lower()
        if lowered == b"authorization":
            bearer = value.decode("latin-1")
        elif lowered == b"x-api-key":
            api_key = value.decode("latin-1")
    if bearer and bearer.lower().startswith("bearer ") and bearer[7:].strip():
        return bearer[7:].strip()
    return api_key


class _TokenGuard:
    """ASGI middleware that rejects any HTTP request lacking the shared token.

    Non-HTTP scopes (the ASGI lifespan) pass through untouched so the wrapped
    app still starts and shuts down normally.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or _extract_access_token(
            scope.get("headers", [])
        ) == self.token:
            await self.app(scope, receive, send)
            return
        from starlette.responses import PlainTextResponse

        await PlainTextResponse("invalid or missing access token", status_code=401)(
            scope, receive, send
        )


def main() -> None:
    """Run the MCP server: stdio by default, streamable HTTP when
    ``MCP_HTTP_TRANSPORT=http``.

    The HTTP mode is fail-closed: without a non-empty ``MCP_HTTP_TOKEN`` the
    server exits before binding instead of serving an unauthenticated
    endpoint. Host/port come from ``MCP_HTTP_HOST`` / ``MCP_HTTP_PORT``.
    """
    transport = (os.environ.get("MCP_HTTP_TRANSPORT") or "stdio").strip().lower()
    if transport in ("", "stdio"):
        mcp.run()
        return
    if transport not in ("http", "streamable-http"):
        raise SystemExit(
            f"Unsupported MCP_HTTP_TRANSPORT={transport!r} (use stdio or http)"
        )
    token = os.environ.get("MCP_HTTP_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "MCP_HTTP_TOKEN is required when MCP_HTTP_TRANSPORT=http: refusing to "
            "serve an unauthenticated MCP endpoint"
        )
    import uvicorn

    app = _TokenGuard(mcp.http_app(transport="http"), token)
    uvicorn.run(
        app,
        host=os.environ.get("MCP_HTTP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_HTTP_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
