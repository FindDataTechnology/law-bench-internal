"""Guard: all LLM calls go through ``src.llm`` (spec: llm-orchestration, R3).

The spec requires LLM calls to converge on a single replaceable call point.
A module that imports a specific LLM SDK directly (``litellm`` / ``crewai`` /
``openai``) bypasses that point — and when the SDK is later swapped or removed,
such a module breaks only at call time, which mocked tests never exercise
(2026-11-22: three ``src/clauses`` modules still called ``litellm.completion``
after litellm was dropped from pyproject; every test mocked the LLM and stayed
green). This test fails if any source module imports an LLM SDK directly
outside the allowed single point.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
#: Modules allowed to import an LLM SDK directly. Everything else must use src.llm.
ALLOWED = {
    "src/llm.py",           # the single call point
    "src/eval/judge.py",    # deepeval GPTModel (a different, testable seam)
}
SDKS = ("import litellm", "from litellm", "import crewai", "from crewai")


def test_only_single_point_imports_llm_sdk():
    offenders = []
    for path in (REPO / "src").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for sdk in SDKS:
            if sdk in text:
                offenders.append(f"{rel}: {sdk}")
    assert not offenders, (
        "these modules import an LLM SDK directly instead of going through "
        "src.llm (spec: llm-orchestration, single replaceable call point):\n  "
        + "\n  ".join(offenders)
    )
