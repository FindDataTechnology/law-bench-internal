"""Registration smoke tests: the server advertises the full expected tool set,
every tool module imports without error, and each tool carries its concept tag.
"""

from __future__ import annotations

import asyncio

# The canonical, expected tool set. Any drift (a mis-named or unregistered
# ``@mcp.tool``, or a removed tool) fails this test.
EXPECTED_TOOLS = {
    # contracts (generate + evaluate)
    "contract_generate",
    "contract_evaluate",
    # rubrics (rubric + criterion management)
    "rubric_list",
    "rubric_get",
    "rubric_create",
    "rubric_update",
    "rubric_delete",
    "criterion_add",
    "criterion_update",
    "criterion_delete",
    "criterion_reorder",
    # prompts
    "prompt_list",
    "prompt_get",
    "prompt_create",
    "prompt_update",
    "prompt_delete",
    # eval (compare orchestration + run reads)
    "compare_run",
    "compare_list",
    "compare_get",
    "compare_matrix",
    "run_list",
    "run_get",
    "run_draft",
    # search
    "search_clauses",
    # law (law-info + legal-references reads)
    "law_types",
    "law_info",
    "law_references",
    # tags (read-only vocabulary + validation)
    "tag_vocab_list",
    "tag_validate",
}

# Each tool's concept group. FastMCP exposes the ``tags=`` kwarg via the tool's
# ``meta.fastmcp.tags`` list, so a tag-aware client can read the grouping.
EXPECTED_TAGS = {
    "contract_generate": "contracts",
    "contract_evaluate": "contracts",
    "rubric_list": "rubrics",
    "rubric_get": "rubrics",
    "rubric_create": "rubrics",
    "rubric_update": "rubrics",
    "rubric_delete": "rubrics",
    "criterion_add": "rubrics",
    "criterion_update": "rubrics",
    "criterion_delete": "rubrics",
    "criterion_reorder": "rubrics",
    "prompt_list": "prompts",
    "prompt_get": "prompts",
    "prompt_create": "prompts",
    "prompt_update": "prompts",
    "prompt_delete": "prompts",
    "compare_run": "eval",
    "compare_list": "eval",
    "compare_get": "eval",
    "compare_matrix": "eval",
    "run_list": "eval",
    "run_get": "eval",
    "run_draft": "eval",
    "search_clauses": "search",
    "law_types": "law",
    "law_info": "law",
    "law_references": "law",
    "tag_vocab_list": "tags",
    "tag_validate": "tags",
}

# Every tool module that registers ``@mcp.tool`` decorators on import.
_TOOL_MODULES = (
    "fd_coding_law_bench_mcp.tools.compare",
    "fd_coding_law_bench_mcp.tools.evaluate",
    "fd_coding_law_bench_mcp.tools.generate",
    "fd_coding_law_bench_mcp.tools.law_info",
    "fd_coding_law_bench_mcp.tools.prompts",
    "fd_coding_law_bench_mcp.tools.rag",
    "fd_coding_law_bench_mcp.tools.rubrics",
    "fd_coding_law_bench_mcp.tools.tags",
)


def _list_tools():
    from fastmcp import Client

    from fd_coding_law_bench_mcp.server import mcp

    async def _list():
        async with Client(mcp) as client:
            return await client.list_tools()

    return asyncio.run(_list())


def test_advertised_tools_match_expected_set():
    tools = _list_tools()
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    extra = names - EXPECTED_TOOLS
    assert not missing, f"missing tools: {sorted(missing)}"
    assert not extra, f"unexpected extra tools: {sorted(extra)}"


def test_each_tool_carries_its_concept_tag():
    tools = {t.name: t for t in _list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    for name, concept in EXPECTED_TAGS.items():
        meta = tools[name].meta or {}
        fastmcp_meta = meta.get("fastmcp") or {}
        tags = fastmcp_meta.get("tags", [])
        assert concept in tags, (
            f"{name} expected concept tag {concept!r}, got tags={tags!r}"
        )


def test_tool_modules_import_cleanly():
    import importlib

    for mod_name in _TOOL_MODULES:
        # A failure here means a tool module has an import-time error (e.g. a
        # bad ``from ..server import mcp`` or a stray top-level ``src.*`` import).
        assert importlib.import_module(mod_name) is not None
