"""Simple chat endpoint - runs the graph end-to-end, auto-resolving interrupts.

This is a pragmatic MVP that avoids the CopilotKit runtime + LangGraph Server
complexity. The graph runs from generate_v1 to export, with the 3 interrupt
checkpoints auto-resolved (accept all suggestions, fill slots with defaults,
approve final). Returns the final state as JSON.

The full CopilotKit HITL experience (interactive checkpoints) requires
langgraph-api (LangGraph Server) which is a heavy dep; this endpoint gets a
working chat immediately.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    contract_type: str = "sale"
    scenario: str | None = "农产品买卖"
    thread_id: str | None = None


class ChatResponse(BaseModel):
    thread_id: str
    contract_type: str
    draft: str
    slots: list[str]
    reviews: list[dict]
    synthesized_suggestions: list[dict]
    quiz_items: list[dict]
    eval_result: dict
    deepeval_scores: dict
    node_timings: dict
    model_calls: list[dict]
    errors: list[dict]
    total_duration: float


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> Any:
    """Run the review-agent graph end-to-end, auto-resolving checkpoints."""
    from agent.graph import build_review_graph
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    graph = build_review_graph(checkpointer=MemorySaver())
    thread_id = req.thread_id or f"chat-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "contract_type": req.contract_type,
        "tags": {"scenario": req.scenario, "stance": "balanced"},
        "task_desc": req.message,
        "thread_id": thread_id,
        "node_timings": {},
        "model_calls": [],
        "errors": [],
    }

    # Default slot values for the auto-resolved quiz checkpoint.
    default_slots = {
        "party_a": "买方公司",
        "party_b": "卖方公司",
        "subject": req.contract_type,
        "quantity": "1",
        "amount": "10000元",
        "delivery_address": "合同约定地点",
        "delivery_date": "2026-08-30",
        "payment_method": "银行转账",
        "penalty_rate": "0.05",
        "jurisdiction": "合同签订地人民法院",
    }

    # Run the graph, auto-resolving each interrupt.
    import time

    t0 = time.perf_counter()
    state = await graph.ainvoke(initial_state, config=config)

    # Loop through interrupts, auto-resolving each.
    for _ in range(10):  # safety cap
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            break
        node = snapshot.next[0]

        # Determine the resume value based on which checkpoint.
        if "triage" in node:
            resume = {"accepted": state.get("synthesized_suggestions", [])}
        elif "quiz" in node:
            # Fill slots with defaults; backfill any missing from quiz_items.
            quiz_items = state.get("quiz_items", [])
            slot_values = {}
            for item in quiz_items:
                slot = item.get("slot", "")
                slot_values[slot] = default_slots.get(slot, f"测试值_{slot}")
            resume = slot_values
        elif "review" in node or "approve" in node:
            resume = {"approval": "approved"}
        else:
            resume = {}

        state = await graph.ainvoke(Command(resume=resume), config=config)

    elapsed = time.perf_counter() - t0

    return ChatResponse(
        thread_id=thread_id,
        contract_type=req.contract_type,
        draft=state.get("draft_v2") or state.get("draft_v1") or "",
        slots=state.get("slots") or [],
        reviews=state.get("reviews") or [],
        synthesized_suggestions=state.get("synthesized_suggestions") or [],
        quiz_items=state.get("quiz_items") or [],
        eval_result=state.get("eval_result") or {},
        deepeval_scores=state.get("deepeval_scores") or {},
        node_timings=state.get("node_timings") or {},
        model_calls=state.get("model_calls") or [],
        errors=state.get("errors") or [],
        total_duration=round(elapsed, 2),
    )
