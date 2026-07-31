"""Server-level tests: all five tools are registered, and ``__main__`` imports."""

from __future__ import annotations

import asyncio

EXPECTED_TOOLS = {
    "generate_contract_from_tags",
    "evaluate_contract",
    "list_rubrics",
    "list_runs",
    "rag_search",
}


def test_main_module_importable():
    import fd_coding_law_bench_mcp.__main__ as main_mod

    assert hasattr(main_mod, "_entry")


def test_registers_all_tools():
    from fastmcp import Client

    from fd_coding_law_bench_mcp.server import mcp

    async def _list():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(_list())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}; got: {names}"
