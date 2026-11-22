"""Unit tests for ``src/crew.py``: template loading and orchestrator contract.

Replaces the former CrewAI-crew-assembly assertions (``len(crew.agents)`` /
``len(crew.tasks)``) with the explicit four-step contract this module now owns
(openspec: replace-crewai-with-litellm-orchestration). No LLM call is made here —
``run`` is exercised only through the ``kickoff``-missing-input path and the
pre-retrieval degradation path.
"""

from __future__ import annotations

import pytest

from src.crew import ContractDraftingCrew, _templates_reference, _pre_retrieve
from src.settings import TEMPLATES_DIR, ConfigError


def test_templates_reference_loads_seed_templates():
    ref = _templates_reference()
    assert ref  # non-empty
    expected_stems = sorted(p.stem for p in TEMPLATES_DIR.glob("*.md"))
    assert expected_stems  # templates exist in the repo
    for stem in expected_stems:
        assert f"### 模板：{stem}" in ref


def test_templates_reference_empty_when_no_templates(tmp_path, monkeypatch):
    monkeypatch.setattr("src.crew.TEMPLATES_DIR", tmp_path)
    assert _templates_reference() == ""


def test_orchestrator_loads_four_steps_from_config():
    """The orchestrator binds the four steps and reads prompts from yaml."""
    crew = ContractDraftingCrew()
    assert set(crew.tasks_config) >= {
        "clarify_requirements",
        "draft_contract",
        "audit_contract",
        "revise_contract",
    }
    assert set(crew.agents_config) >= {"intake_clarifier", "drafter", "auditor"}


def test_kickoff_requires_user_request():
    crew = ContractDraftingCrew()
    with pytest.raises(ConfigError):
        crew.kickoff(inputs={})


def test_pre_retrieve_degrades_when_tools_unavailable(monkeypatch):
    """Retrieval unavailable (both getters return None) → empty reference, no raise."""
    monkeypatch.setattr("src.search.rag_tool.get_rag_tool", lambda: None)
    monkeypatch.setattr("src.law_api.tool.get_law_search_tool", lambda: None)
    assert _pre_retrieve("起草一份服务协议") == ""
