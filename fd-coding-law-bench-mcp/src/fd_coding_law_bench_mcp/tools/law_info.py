"""Law-info & legal-references read tools.

Wrap the read-only helpers in :mod:`src.eval.law_info` (per-contract-type
法律法规 surveys) and :mod:`src.eval.legal_refs` (the pure aggregator that
deduplicates + categorizes the laws cited across those surveys). All read-only;
``NotFoundError`` surfaces as a tool error.

线状态（change domain-first-mcp §8.4，2026-11-24）：**本组的合同装配/评测线已停**
（生成任务 0 条、对比 0 条、提示词 0 条，产物停在 2026-11-11）。工具保持可用且行为
未变——这是「不再作为平台主线」，不是「删除实现」。数据快照归档在工作区
`attic/legal-contract-line-2026-11-24/`。
"""

from __future__ import annotations

import anyio

from ..annotations import annotations_for
from ..server import mcp


@mcp.tool(tags={"legal"}, annotations=annotations_for("law_types"))
async def law_types() -> list[dict]:
    """List contract types that have at least one law_info survey row.

    Returns ``[{key, zh_name, sources}]`` ordered by contract type, where
    ``sources`` lists the sources present for that type (e.g.
    ``["doubao", "deepseek"]``).
    """
    from src.eval.law_info import list_law_info_types as _list

    return await anyio.to_thread.run_sync(_list)


@mcp.tool(tags={"legal"}, annotations=annotations_for("law_info"))
async def law_info(contract_type: str) -> dict:
    """Fetch both sources' survey content for a contract type.

    Parameters:
        contract_type: contract class key.

    Returns ``{type, zh_name, doubao, deepseek}`` where each source field is the
    markdown content string or ``None`` when absent. A type with no law_info row
    raises a tool error.
    """
    from src.eval.law_info import get_law_info as _get

    return await anyio.to_thread.run_sync(_get, contract_type)


@mcp.tool(tags={"legal"}, annotations=annotations_for("law_references"))
async def law_references() -> list[dict]:
    """Aggregate the unique laws referenced across every law_info survey.

    Runs :func:`src.eval.legal_refs.extract_references` over
    :func:`src.eval.law_info.all_law_info`. Returns a list of
    ``{name, category, category_zh, contract_types, sources, occurrences}``
    sorted by category then name. Read-only.
    """
    from src.eval.law_info import all_law_info
    from src.eval.legal_refs import extract_references

    def _go() -> list[dict]:
        return extract_references(all_law_info())

    return await anyio.to_thread.run_sync(_go)
