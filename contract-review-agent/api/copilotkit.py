"""CopilotKit AG-UI integration — mount the LangGraph graph as an HTTP endpoint.

The frontend's CopilotKit provider talks to this endpoint via the AG-UI protocol.
LangGraph's interrupt() checkpoints are bridged to the frontend's
useHumanInTheLoop hook, enabling the three human-in-the-loop checkpoints.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def setup_copilotkit(app: FastAPI) -> None:
    """Mount the review-agent graph at the root path for CopilotKit."""
    try:
        from ag_ui_langgraph import add_langgraph_fastapi_endpoint
        from copilotkit import CopilotKitMiddleware, LangGraphAGUIAgent
    except ImportError as e:
        raise ImportError(
            "CopilotKit dependencies not installed. Run: pip install copilotkit ag-ui-langgraph"
        ) from e

    from agent.graph import build_review_graph

    # Build the graph with checkpointer (AsyncPostgresSaver).
    graph = build_review_graph()

    # Wrap as a CopilotKit-compatible agent.
    agent = LangGraphAGUIAgent(
        name="contract-review-agent",
        description="Multi-model contract review with human checkpoints",
        graph=graph,
    )

    # Add the AG-UI endpoint at /.
    add_langgraph_fastapi_endpoint(
        app=app,
        agent=agent,
        path="/",
        middleware=[CopilotKitMiddleware()],
    )
