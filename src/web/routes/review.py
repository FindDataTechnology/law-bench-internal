"""Human-review routes over eval verdicts (change add-web-human-review).

Two page routes and one decision POST. Every route inherits the app-level
``get_current_user`` dependency (see ``create_app``), so an anonymous browser
navigation 302s to ``/auth/login``; the decision POST additionally requires the
``review:annotate`` scope, which Logto bundles into the ``lawbench-annotator``
role. The annotator stamp is always the session identity — never a form field.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import User, get_current_user, require_scope
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...eval import review as review_store
from ...eval.errors import NotFoundError

read_only_router = APIRouter(tags=["review"])
write_router = APIRouter(tags=["review"])

REVIEW_SCOPE = "review:annotate"


def _annotator_of(user: User) -> str:
    """Stable, readable annotator stamp from the session identity.

    Logto's ``sub`` is the stable id, but it is opaque in reports; the account
    email (or display name) is what an operator recognises. Falls back to
    ``sub`` when neither is present, so a stamp always exists.
    """
    return user.email or user.name or user.sub


def _verdict_labels(batch_type: str) -> dict[str, str]:
    if batch_type == "validity":
        return {"pass": "通过（与标准一致）", "fail": "不通过（与标准不符）"}
    return {"approved": "认可该判定", "rejected": "不认可该判定", "skipped": "跳过"}


@read_only_router.get("/review", include_in_schema=False, name="page_review")
def review_home(
    request: Request,
    batch: str | None = None,
    user: User = Depends(get_current_user),
    db: DbConn = Depends(get_db),
):
    """Batch overview plus the caller's pending queue.

    Any authenticated caller may look; only decisions carry the scope check
    (``require_scope`` on the POST), so the resolved :class:`User` is taken
    straight from ``get_current_user`` rather than through a scope gate.
    """
    batches = review_store.list_batches(db=db)
    selected = batch or (batches[0]["batch_id"] if batches else None)
    tasks = (
        review_store.list_tasks(
            batch_id=selected, status="pending",
            for_annotator=_annotator_of(user), db=db,
        )
        if selected
        else []
    )
    return _templates.TemplateResponse(
        request,
        "review_list.html",
        {
            "batches": batches,
            "selected": selected,
            "tasks": tasks,
            "me": _annotator_of(user),
        },
    )


@read_only_router.get(
    "/review/{task_id}", include_in_schema=False, name="page_review_task"
)
def review_task(
    request: Request,
    task_id: int,
    user: User = Depends(get_current_user),
    db: DbConn = Depends(get_db),
):
    try:
        task = review_store.get_task_detail(task_id, db=db)
    except NotFoundError:
        return _templates.TemplateResponse(
            request, "review_task.html", {"task": None, "task_id": task_id},
            status_code=404,
        )
    return _templates.TemplateResponse(
        request,
        "review_task.html",
        {
            "task": task,
            "verdict_labels": _verdict_labels(task["batch_type"]),
            "me": _annotator_of(user),
        },
    )


@write_router.post(
    "/review/{task_id}/decide",
    include_in_schema=False,
    name="page_review_decide",
)
async def review_decide(
    request: Request,
    task_id: int,
    user: User = Depends(require_scope(REVIEW_SCOPE)),
    db: DbConn = Depends(get_db),
):
    form = await request.form()
    verdict = (form.get("verdict") or "").strip()
    note = (form.get("note") or "").strip()
    try:
        outcome = review_store.decide_task(
            task_id=task_id,
            annotator=_annotator_of(user),
            verdict=verdict,
            note=note,
            db=db,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"review task not found: {task_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not outcome["ok"]:
        return RedirectResponse(
            f"/review/{task_id}?flash={quote('该条目已被其他标注员处理')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/review?flash={quote('已记录判定')}", status_code=303
    )


router = APIRouter(tags=["review"])
router.include_router(read_only_router)
router.include_router(write_router)
