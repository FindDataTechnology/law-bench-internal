"""The single FastMCP server instance + tool registration.

The tool modules are imported at the bottom (after ``mcp`` is defined) so each
can do ``from ..server import mcp`` and register its ``@mcp.tool`` decorators.
``src.*`` imports are deferred to call time inside each tool, keeping server
startup light and avoiding import-time coupling to DB / network backends.
"""

from __future__ import annotations

from fastmcp import FastMCP

mcp: FastMCP = FastMCP("law-bench")

# Importing the tool modules registers their @mcp.tool decorators. Order does
# not matter; the names are re-exported for callers / tests that want them.
from .tools import evaluate as _evaluate  # noqa: E402,F401
from .tools import generate as _generate  # noqa: E402,F401
from .tools import rag as _rag  # noqa: E402,F401


def main() -> None:
    """Run the FastMCP server over the default stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
