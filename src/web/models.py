"""Pydantic request models for the evaluation-rules web API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CriterionIn(BaseModel):
    """A criterion submitted as part of a rubric create/update payload."""

    name: str
    description: str
    guidance: str


class RubricCreate(BaseModel):
    name: str
    context: str
    description: Optional[str] = None
    criteria: list[CriterionIn] = Field(default_factory=list)


class RubricUpdate(BaseModel):
    name: str
    context: str
    description: Optional[str] = None


class CriterionCreate(BaseModel):
    name: str
    description: str
    guidance: str


class CriterionUpdate(BaseModel):
    name: str
    description: str
    guidance: str


class ReorderRequest(BaseModel):
    ordered_criterion_ids: list[int]


class PromptCreate(BaseModel):
    """Payload to create a generation prompt."""

    name: str
    contract_type: str
    purpose: str
    content: str
    description: Optional[str] = None
    prompt_type: Optional[str] = None


class PromptUpdate(BaseModel):
    """Payload to update a generation prompt (full record)."""

    name: str
    contract_type: str
    purpose: str
    content: str
    description: Optional[str] = None
    prompt_type: Optional[str] = None


class CompareCreate(BaseModel):
    """Payload to create and run a prompt compare."""

    contract_type: str
    rubric_name: str
    task_desc: str
    prompts: list[str]
    mode: str = "drafter-only"
    n_drafts: int = 1
    label: Optional[str] = None


class EvaluateSubmitResponse(BaseModel):
    """Response from POST /api/evaluate (202 Accepted)."""

    run_id: int
    status: str


class EvaluateRunSummary(BaseModel):
    """Summary row for GET /api/evaluate (list)."""

    id: int
    rubric_name: str
    status: str
    score: Optional[float] = None
    all_pass: Optional[bool] = None
    n_passed: Optional[int] = None
    n_criteria: Optional[int] = None
    error_message: Optional[str] = None
    judge_model: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class EvaluateRunDetail(BaseModel):
    """Full detail for GET /api/evaluate/{run_id}."""

    id: int
    rubric_name: str
    status: str
    contract_text: str
    score: Optional[float] = None
    all_pass: Optional[bool] = None
    n_passed: Optional[int] = None
    n_criteria: Optional[int] = None
    results: Optional[dict] = None
    error_message: Optional[str] = None
    judge_model: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
