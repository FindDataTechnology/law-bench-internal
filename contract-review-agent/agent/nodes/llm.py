"""Shared LLM call helper for review-agent nodes.

Uses litellm (already a dependency via the law-bench venv) pointed at the
OpenAI-compatible relay. Returns the text, token usage, and latency so each
node can record per-model metrics for the agent_runs table.

All nodes go through ``call_llm`` so model-call accounting is centralized.
"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()
# litellm fetches a remote model-cost-map on first call; force local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")


async def call_llm(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> dict:
    """Call the relay via litellm and return {text, tokens, cost, latency}.

    Robust: on any LLM/parse failure returns ``{error, text: "", tokens: 0}``
    so a node never crashes the graph — it just records an error.
    """
    import litellm

    t0 = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = await litellm.acompletion(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        cost = float(
            litellm.completion_cost(completion_response=resp)
            if _cost_available(resp)
            else 0.0
        )
        latency = time.perf_counter() - t0
        return {"text": text, "tokens": tokens, "cost": cost, "latency": latency}
    except Exception as exc:  # noqa: BLE001
        return {
            "text": "",
            "tokens": 0,
            "cost": 0.0,
            "latency": time.perf_counter() - t0,
            "error": str(exc),
        }


def _cost_available(resp: Any) -> bool:
    """litellm.completion_cost raises if it can't price the model; guard it."""
    try:
        return bool(getattr(resp, "model", ""))
    except Exception:
        return False
