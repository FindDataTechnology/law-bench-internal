"""JSON API for evaluation rubrics and criteria.

All write paths delegate to `src/eval/manage.py`, which raises `ManageError`
subclasses; those are mapped to HTTP statuses by exception handlers registered
in `src/web/app.py`. Routes here therefore stay thin: call the service, return
its dict. Each handler takes a ``db`` dependency (see ``src/web/deps.py``) so
tests can point the layer at a throwaway DB instead of the dev one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.eval import manage as M
from src.eval.compare import build_matrix, load_prompts, run_compare
from src.eval.store import get_compare, get_run_draft, list_compares
from src.settings import DEFAULT_DB, EXTRACT_SCRIPT, REPO_ROOT

from ..deps import get_db
from ..models import (
    CompareCreate,
    CriterionCreate,
    CriterionUpdate,
    PromptCreate,
    PromptUpdate,
    ReorderRequest,
    RubricCreate,
    RubricUpdate,
)

router = APIRouter(prefix="/api", tags=["evaluation-rules"])


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


# --- read ------------------------------------------------------------------ #


@router.get("/rubrics")
def list_rubrics(db: Path = Depends(get_db)) -> list[dict]:
    """All rubrics with source/context/criterion count."""
    return M.list_rubrics_with_counts(db_path=db)


@router.get("/rubrics/{name}")
def get_rubric(name: str, db: Path = Depends(get_db)) -> dict:
    """A rubric's metadata and its ordered criteria."""
    return M.get_rubric_detail(name, db_path=db)


# --- rubric writes --------------------------------------------------------- #


@router.post("/rubrics", status_code=201)
def create_rubric(body: RubricCreate, db: Path = Depends(get_db)) -> dict:
    return M.create_rubric(
        body.name,
        body.context,
        body.description,
        [c.model_dump() for c in body.criteria],
        db_path=db,
    )


@router.patch("/rubrics/{name}")
def update_rubric(name: str, body: RubricUpdate, db: Path = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)  # raises NotFoundError if missing
    return M.update_rubric(
        detail["id"], body.name, body.context, body.description, db_path=db
    )


@router.delete("/rubrics/{name}")
def delete_rubric(name: str, db: Path = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    M.delete_rubric(detail["id"], db_path=db)
    return {"deleted": name}


# --- criterion writes ------------------------------------------------------ #


@router.post("/rubrics/{name}/criteria", status_code=201)
def add_criterion(name: str, body: CriterionCreate, db: Path = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    return M.add_criterion(
        detail["id"], body.name, body.description, body.guidance, db_path=db
    )


# Defined before the {cid} routes so "/criteria/reorder" is not matched as an int cid.
@router.post("/rubrics/{name}/criteria/reorder")
def reorder_criteria(name: str, body: ReorderRequest, db: Path = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    ordered = M.reorder_criteria(detail["id"], body.ordered_criterion_ids, db_path=db)
    return {"ordered_criterion_ids": ordered}


@router.patch("/rubrics/{name}/criteria/{cid}")
def update_criterion(
    name: str, cid: int, body: CriterionUpdate, db: Path = Depends(get_db)
) -> dict:
    return M.update_criterion(cid, body.name, body.description, body.guidance, db_path=db)


@router.delete("/rubrics/{name}/criteria/{cid}")
def delete_criterion(name: str, cid: int, db: Path = Depends(get_db)) -> dict:
    M.delete_criterion(cid, db_path=db)
    return {"deleted": cid}


# --- prompts --------------------------------------------------------------- #


@router.get("/prompts")
def list_prompts(db: Path = Depends(get_db)) -> list[dict]:
    """All generation prompts (without content bodies)."""
    return M.list_prompts(db_path=db)


@router.get("/prompts/{name}")
def get_prompt(name: str, db: Path = Depends(get_db)) -> dict:
    """A prompt's full record including its content."""
    return M.get_prompt(name, db_path=db)


@router.post("/prompts", status_code=201)
def create_prompt(body: PromptCreate, db: Path = Depends(get_db)) -> dict:
    return M.create_prompt(
        body.name,
        body.contract_type,
        body.purpose,
        body.content,
        body.description,
        body.prompt_type,
        db_path=db,
    )


@router.patch("/prompts/{name}")
def update_prompt(name: str, body: PromptUpdate, db: Path = Depends(get_db)) -> dict:
    detail = M.get_prompt(name, db_path=db)  # raises NotFoundError if missing
    return M.update_prompt(
        detail["id"],
        body.name,
        body.contract_type,
        body.purpose,
        body.content,
        body.description,
        body.prompt_type,
        db_path=db,
    )


@router.delete("/prompts/{name}")
def delete_prompt(name: str, db: Path = Depends(get_db)) -> dict:
    detail = M.get_prompt(name, db_path=db)
    M.delete_prompt(detail["id"], db_path=db)
    return {"deleted": name}


# --- compare --------------------------------------------------------------- #


@router.get("/compare")
def list_compares_route(db: Path = Depends(get_db)) -> list[dict]:
    """Recent compare runs (compare-level fields only)."""
    return list_compares(db_path=db)


@router.get("/compare/{compare_id}")
def get_compare_route(compare_id: int, db: Path = Depends(get_db)) -> dict:
    """Full grouped compare result with a derived criteria × prompts matrix.

    ``draft_text`` is excluded (lazy-fetched via ``/run/{run_id}/draft``).
    """
    try:
        compare = get_compare(compare_id, db_path=db)
    except KeyError:
        return _err(404, f"Compare not found: {compare_id}")
    return {**compare, "matrix": build_matrix(compare)}


@router.post("/compare", status_code=201)
def create_compare(body: CompareCreate, db: Path = Depends(get_db)) -> dict:
    """Create and run a compare synchronously.

    Runs the drafter-only generation + the real judge for each prompt/draft.
    Large compares (many prompts × high ``n_drafts``) can take minutes; for
    those prefer the CLI (``python -m src.eval.compare``). Async-with-progress
    is a tracked follow-up.
    """
    prompts = load_prompts(body.prompts, db_path=db)  # raises NotFoundError -> 404
    compare = run_compare(
        body.contract_type,
        body.rubric_name,
        body.task_desc,
        prompts,
        mode=body.mode,
        n_drafts=body.n_drafts,
        label=body.label,
        db_path=db,
    )
    return {**compare, "matrix": build_matrix(compare)}


@router.get("/compare/{compare_id}/run/{run_id}/draft")
def get_run_draft_route(compare_id: int, run_id: int, db: Path = Depends(get_db)) -> dict:
    """Lazy-fetch a single run's ``draft_text`` (kept out of the default payload)."""
    try:
        return get_run_draft(compare_id, run_id, db_path=db)
    except KeyError:
        return _err(404, f"Run {run_id} not found in compare {compare_id}")


# --- harbor re-extraction -------------------------------------------------- #


def run_harbor_extraction(db_path: Path = DEFAULT_DB) -> tuple[int, str, str]:
    """Run the harbor extraction script; return (returncode, stdout, stderr).

    Shared by the JSON endpoint and the HTML "Re-extract harbor" control so the
    two cannot diverge.
    """
    proc = subprocess.run(
        [sys.executable, str(EXTRACT_SCRIPT), "--db", str(db_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


@router.post("/harbor/extract")
def harbor_extract(db: Path = Depends(get_db)) -> JSONResponse:
    """Re-run the harbor extraction script; return its summary + refreshed rubrics.

    Surface a non-zero exit as an error (e.g. harbor not installed).
    """
    if not EXTRACT_SCRIPT.is_file():
        return _err(500, f"extraction script not found: {EXTRACT_SCRIPT}")
    code, out, err = run_harbor_extraction(db_path=db)
    if code != 0:
        return _err(500, f"harbor extraction failed (exit {code}): {(err or '').strip()}")
    return JSONResponse(
        {"returncode": code, "stdout": out, "rubrics": M.list_rubrics_with_counts(db_path=db)}
    )
