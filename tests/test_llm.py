"""Unit tests for ``src/llm.py``."""

from __future__ import annotations

import pytest

from src.llm import get_llm
from src.settings import ConfigError


@pytest.fixture(autouse=True)
def _gateway_env(monkeypatch):
    """The wrapper builds an OpenAI client, which needs a base URL + key."""
    monkeypatch.setenv("OPENAI_API_BASE", "https://router.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_get_llm_uses_configured_model(monkeypatch):
    monkeypatch.setenv("DRAFTER_MODEL", "openai/glm-5.2")
    monkeypatch.delenv("DRAFTER_TEMPERATURE", raising=False)
    monkeypatch.delenv("DRAFTER_MAX_TOKENS", raising=False)
    llm = get_llm("DRAFTER")
    # the litellm-style ``openai/`` prefix is stripped for the openai SDK
    assert llm.model == "glm-5.2"


def test_get_llm_strips_prefix_only_when_present(monkeypatch):
    monkeypatch.setenv("DRAFTER_MODEL", "glm-5.2")
    llm = get_llm("DRAFTER")
    assert llm.model == "glm-5.2"


def test_get_llm_applies_defaults(monkeypatch):
    monkeypatch.setenv("INTAKE_MODEL", "openai/deepseek-v4-flash")
    monkeypatch.delenv("INTAKE_TEMPERATURE", raising=False)
    monkeypatch.delenv("INTAKE_MAX_TOKENS", raising=False)
    llm = get_llm("INTAKE")
    assert llm.temperature == 0.2
    # default max_tokens is large enough for reasoning models
    assert llm.max_tokens == 200000


def test_get_llm_applies_overrides(monkeypatch):
    monkeypatch.setenv("AUDITOR_MODEL", "openai/glm-5.2")
    monkeypatch.setenv("AUDITOR_TEMPERATURE", "0.1")
    monkeypatch.setenv("AUDITOR_MAX_TOKENS", "4000")
    llm = get_llm("AUDITOR")
    assert llm.temperature == 0.1
    assert llm.max_tokens == 4000


def test_get_llm_missing_model_raises_config_error(monkeypatch):
    monkeypatch.delenv("DRAFTER_MODEL", raising=False)
    with pytest.raises(ConfigError, match="DRAFTER_MODEL"):
        get_llm("DRAFTER")


def test_get_llm_missing_gateway_raises_config_error(monkeypatch):
    monkeypatch.setenv("DRAFTER_MODEL", "openai/glm-5.2")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_BASE"):
        get_llm("DRAFTER")
