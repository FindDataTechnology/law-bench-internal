"""
Contract drafting orchestration: clarify → draft → audit → revise.

Replaces the former CrewAI ``@CrewBase`` crew (openspec:
replace-crewai-with-litellm-orchestration). CrewAI's ``Crew(process=sequential)``
injected each task's output into the next task's context implicitly; this module
makes that passing **explicit** (spec: llm-orchestration — explicit input
provenance). Prompt text still comes verbatim from ``config/agents.yaml`` and
``config/tasks.yaml``.

Retrieval: the old crew attached ``contract_search`` / ``law_search`` as
LLM-callable tools and let the model decide when to retrieve. Here the orchestrator
pre-retrieves once with the user request and injects the results as reference
material into the draft step (design D3, option B). Degradation is unchanged: a
retrieval tool that is unavailable or fails yields "", and drafting proceeds.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.settings import TEMPLATES_DIR, ConfigError
from .llm import get_llm

_CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((_CONFIG_DIR / name).read_text(encoding="utf-8"))


def _templates_reference() -> str:
    """Load all seed templates into a reference block for the drafter.

    The drafter is told to follow template structure; this puts the actual
    template content in-context so it can mirror standard clauses.
    """
    if not TEMPLATES_DIR.is_dir():
        return ""
    parts = []
    for tpl in sorted(TEMPLATES_DIR.glob("*.md")):
        parts.append(f"### 模板：{tpl.stem}\n\n{tpl.read_text(encoding='utf-8').strip()}\n")
    return "\n".join(parts)


def _system_prompt(agent_cfg: dict) -> str:
    """Compose the system prompt from an agents.yaml entry (role/goal/backstory)."""
    return (
        f"角色：{agent_cfg.get('role', '').strip()}\n"
        f"目标：{agent_cfg.get('goal', '').strip()}\n"
        f"背景：{agent_cfg.get('backstory', '').strip()}"
    )


def _pre_retrieve(user_request: str) -> str:
    """Run contract + law retrieval once with the user request; return reference text.

    Both tools degrade silently: disabled/unavailable/failed → empty contribution.
    This mirrors the old crew's "attach a tool that returns '' on failure" contract
    while removing the model's discretion over whether/when to retrieve.
    """
    blocks: list[str] = []
    try:
        from src.search.rag_tool import get_rag_tool

        tool = get_rag_tool()
        if tool is not None:
            text = tool.run_contract_search(user_request)
            if text:
                blocks.append("【历史合同/模板检索】\n" + text)
    except Exception:  # noqa: BLE001 - degradation: retrieval unavailable -> proceed
        pass
    try:
        from src.law_api.tool import get_law_search_tool

        tool = get_law_search_tool()
        if tool is not None:
            text = tool.run_law_search(user_request)
            if text:
                blocks.append("【法律法规检索】\n" + text)
    except Exception:  # noqa: BLE001 - degradation: retrieval unavailable -> proceed
        pass
    return "\n\n".join(blocks)


class DraftingResult:
    """Minimal result object mirroring the old ``CrewOutput`` usage (``.raw``)."""

    def __init__(self, raw: str) -> None:
        self.raw = raw


class ContractDraftingCrew:
    """Sequential four-step drafting orchestrator (replaces the CrewAI crew).

    Kept as a class with a ``.crew()`` facade so ``main.py`` and the existing
    call pattern stay unchanged; ``.crew()`` returns an object exposing
    ``kickoff(inputs={"user_request": ...}) -> DraftingResult``.
    """

    def __init__(self) -> None:
        self.agents_config = _load_yaml("agents.yaml")
        self.tasks_config = _load_yaml("tasks.yaml")

    def _step(self, role: str, agent_key: str, task_key: str, user: str) -> str:
        system = _system_prompt(self.agents_config[agent_key])
        llm = get_llm(role)
        return llm.call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    def run(self, user_request: str) -> str:
        """clarify → draft → audit → revise; return the final contract text."""
        # 1) clarify
        clarify_desc = self.tasks_config["clarify_requirements"]["description"].format(
            user_request=user_request
        )
        clarify_out = self._step("INTAKE", "intake_clarifier", "clarify_requirements", clarify_desc)

        # 2) draft (user = task desc + clarify output + pre-retrieved reference + templates)
        draft_desc = self.tasks_config["draft_contract"]["description"]
        draft_user = f"{draft_desc}\n\n【结构化需求】\n{clarify_out}"
        retrieval = _pre_retrieve(user_request)
        if retrieval:
            draft_user += f"\n\n【参考检索材料】\n{retrieval}"
        reference = _templates_reference()
        if reference:
            draft_user += (
                "\n\n以下为参考模板，请参考其结构与标准条款，按本次需求选用并调整：\n\n"
                f"{reference}"
            )
        draft_out = self._step("DRAFTER", "drafter", "draft_contract", draft_user)

        # 3) audit (user = task desc + the draft itself)
        audit_desc = self.tasks_config["audit_contract"]["description"]
        audit_user = f"{audit_desc}\n\n【待审合同草案】\n{draft_out}"
        audit_out = self._step("AUDITOR", "auditor", "audit_contract", audit_user)

        # 4) revise (user = task desc + original draft + audit report)
        revise_desc = self.tasks_config["revise_contract"]["description"]
        revise_user = (
            f"{revise_desc}\n\n【原合同草案】\n{draft_out}\n\n【审核意见】\n{audit_out}"
        )
        return self._step("DRAFTER", "drafter", "revise_contract", revise_user)

    def crew(self) -> "ContractDraftingCrew":
        """Facade for the old ``.crew()`` call site; returns self."""
        return self

    def kickoff(self, inputs: dict) -> DraftingResult:
        """Facade for the old ``crew.kickoff(inputs=...)`` call site."""
        user_request = inputs.get("user_request")
        if not user_request:
            raise ConfigError("kickoff requires inputs={'user_request': ...}")
        return DraftingResult(self.run(user_request))
