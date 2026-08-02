"""Server-level tests: the full tool set is registered, and ``__main__`` imports."""

from __future__ import annotations

import asyncio

EXPECTED_TOOLS = {
    "contract_generate",
    "contract_evaluate",
    "clause_list",
    "clause_get",
    "clause_update",
    "clause_delete",
    "clause_review",
    "pipeline_run",
    "pipeline_list",
    "pipeline_get",
    "rubric_list",
    "rubric_get",
    "rubric_create",
    "rubric_update",
    "rubric_delete",
    "criterion_add",
    "criterion_update",
    "criterion_delete",
    "criterion_reorder",
    "prompt_list",
    "prompt_get",
    "prompt_create",
    "prompt_update",
    "prompt_delete",
    "compare_run",
    "compare_list",
    "compare_get",
    "compare_matrix",
    "run_list",
    "run_get",
    "run_draft",
    "search_clauses",
    "law_types",
    "law_info",
    "law_references",
    "tag_vocab_list",
    "tag_validate",
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
    assert names == EXPECTED_TOOLS, f"missing: {EXPECTED_TOOLS - names}; extra: {names - EXPECTED_TOOLS}"
