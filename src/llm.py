"""
LLM factory: an OpenAI-SDK chat wrapper built from environment variables per role.

Replaced the former ``crewai.LLM``/litellm dependency (openspec:
replace-crewai-with-litellm-orchestration). crewai sat on ``mcp<2`` and blocked
the MCP framework 4.x upgrade. It first went to litellm, but every LLM call in
this repo already targets an OpenAI-compatible gateway (the 萬星/token router)
via the openai SDK elsewhere (``src/eval/judge.py``, ``src/bench/lane.py``), so
litellm added a dependency for no extra capability — this wrapper uses the
openai SDK directly, like the rest of the repo.

Reads:
- {ROLE}_MODEL
- {ROLE}_TEMPERATURE (optional, default 0.2)
- {ROLE}_MAX_TOKENS (optional, default 200000)
- OPENAI_API_BASE / OPENAI_API_KEY (the OpenAI-compatible gateway)

Model ids in ``.env`` keep the litellm-style ``openai/`` prefix (they predate
this change); it is stripped before the openai SDK sees it, mirroring
``_strip_litellm_prefix`` in ``src/eval/judge.py``.

max_tokens defaults to 200000 (not 4096): the router serves reasoning models
(deepseek-v4.1-flash et al.) whose completion budget is consumed by
``reasoning_tokens`` before any visible content is produced. Measured
2026-11-22: a full contract draft needs ~5.6k visible tokens but the reasoning
model burns ~4-6k reasoning tokens first — at max_tokens=4096 the response is
empty with finish_reason=length (the old crewai "Invalid response from LLM
call - None or empty" failure). A high ceiling costs nothing when unused (you
pay for tokens actually generated) but removes the silent-empty failure.
"""

import os

from openai import OpenAI

from src.settings import ConfigError


def _strip_prefix(model: str) -> str:
    """Drop the litellm-style ``openai/`` prefix the openai SDK does not expect.

    Same rule as ``src/eval/judge.py:_strip_litellm_prefix`` — .env model ids
    carry ``openai/<model>``; the gateway wants ``<model>``.
    """
    return model.split("/", 1)[1] if model.startswith("openai/") else model


class LLM:
    """Thin openai-SDK chat wrapper: ``call(messages) -> str``.

    Kept deliberately small so the orchestration steps depend only on
    ``{role, content}`` message lists and a plain-text reply, never on a
    specific SDK's response objects (spec: llm-orchestration — single
    replaceable call point).
    """

    def __init__(self, model: str, temperature: float, max_tokens: int) -> None:
        self.model = _strip_prefix(model)
        self.temperature = temperature
        self.max_tokens = max_tokens
        base = os.getenv("OPENAI_API_BASE")
        key = os.getenv("OPENAI_API_KEY")
        if not base or not key:
            raise ConfigError(
                "OPENAI_API_BASE / OPENAI_API_KEY not set — the LLM gateway "
                "endpoint is required to reach the model."
            )
        self._client = OpenAI(base_url=base, api_key=key)

    def call(self, messages: list[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        choice = resp.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            # Silent-empty is the failure mode that let a reasoning model at
            # max_tokens=4096 return "" and have it treated as a draft. Make it
            # loud: an empty completion is an error, not a valid contract step.
            raise ConfigError(
                f"LLM returned empty content (model={self.model}, "
                f"finish_reason={choice.finish_reason}). If this is a reasoning "
                f"model, raise {self.model} max_tokens (consumed by reasoning_tokens)."
            )
        return content


def get_llm(role: str) -> LLM:
    """
    Get an LLM instance configured for the given role.

    Args:
        role: Role name in uppercase, e.g. "DRAFTER"

    Returns:
        Configured LLM instance

    Raises:
        ConfigError: If {ROLE}_MODEL is not set in environment
    """
    model = os.getenv(f"{role}_MODEL")
    if not model:
        raise ConfigError(
            f"{role}_MODEL is not set. Copy .env.example to .env and fill in the "
            f"model for the {role} role."
        )
    temperature = float(os.getenv(f"{role}_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv(f"{role}_MAX_TOKENS", "200000"))

    return LLM(model=model, temperature=temperature, max_tokens=max_tokens)


def completion(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """One-shot chat completion against the OpenAI-compatible gateway.

    Shared helper for call sites that need a raw ``(model, messages)`` call with
    explicit temperature/max_tokens (e.g. ``src/clauses/audit.py`` etc.) rather
    than a role-bound :class:`LLM`. Replaces the former direct
    ``litellm.completion`` calls (openspec:
    replace-crewai-with-litellm-orchestration — litellm removed, openai SDK used
    everywhere). Returns the visible text (may be empty; callers handle that).
    """
    base = os.getenv("OPENAI_API_BASE")
    key = os.getenv("OPENAI_API_KEY")
    if not base or not key:
        raise ConfigError(
            "OPENAI_API_BASE / OPENAI_API_KEY not set — the LLM gateway "
            "endpoint is required to reach the model."
        )
    client = OpenAI(base_url=base, api_key=key)
    resp = client.chat.completions.create(
        model=_strip_prefix(model),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens if max_tokens is not None else 200000,
    )
    return resp.choices[0].message.content or ""

