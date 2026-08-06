"""export node — generate DOCX/PDF artifact via existing contract_generate tool.

The final step before saving metrics: render the draft_v2 as a real DOCX (and/or
PDF), upload it, and record the download URL(s) in the state so the frontend can
offer downloads. We reuse the law-bench ``contract_generate`` function that's
already exposed via MCP/HTTP.
"""
from __future__ import annotations

import asyncio
import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState


def _run_export(contract_type: str, scenario: str | None, stance: str | None, tags: dict) -> dict:
    """Synchronous export call; wraps async in thread."""
    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    try:
        res = contract_generate(
            contract_type=contract_type,
            format="both",  # both docx + pdf
            tags=tags,
            stance=stance,
            custom_clause_ids=None,
        )
        # {docx_path, pdf_path, body_text, slots, instructions, law_refs, diagnostics}
        return {"docx_path": res.get("docx_path"), "pdf_path": res.get("pdf_path")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def export_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Generate final DOCX/PDF; record paths in state."""
    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                res = new_loop.run_until_complete(_run_export_async(state))
            finally:
                new_loop.close()
        else:
            res = await _run_export_async(state)
    except RuntimeError:
        res = await _run_export_async(state)

    elapsed = time.perf_counter() - t0
    return {
        "export_paths": res,
        "current_stage": "export",
        "node_timings": {**(state.get("node_timings") or {}),
                         "export": round(elapsed, 3)},
        "errors": errors,
    }


async def _run_export_async(state: ReviewState) -> dict:
    """Async wrapper around export call."""
    import anyio

    return await anyio.to_thread.run_sync(
        _run_export,
        state.get("contract_type", ""),
        (state.get("tags") or {}).get("scenario"),
        (state.get("tags") or {}).get("stance"),
        state.get("tags", {}),
    )
