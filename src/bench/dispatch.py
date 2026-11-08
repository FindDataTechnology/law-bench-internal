"""Batch dispatch: turn estate gaps into assigned tasks (§4.7).

The estate matrix answers "what is missing where". The next operator action is
"give this to someone", and doing that by hand for a dozen dead sub-domains is
exactly the kind of chore that stops a domain tree from being maintained.

Two rules shape this module:

- **Confirmation is a separate page, and loading the estate writes nothing.** A
  batch that creates N tasks as a side effect of rendering a filtered list would
  be one accidental refresh away from N duplicates.
- **A gap that already has an open task is not dispatched again.** The check is
  on the task's ``target_key`` (the pillar) so repeated confirmations converge
  instead of piling up. "Already assigned" is reported, not silently skipped.

Nothing here decides *who*: the caller passes an assignee string (a person or a
fleet). Filling in a default owner would be a policy this module has no basis
for.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from . import authoring, estate

#: Pillar → what the assignee is being asked to do. Kept next to the gap
#: vocabulary (``estate.PILLARS``) so a new pillar cannot be dispatched with a
#: blank title.
GAP_TASKS: dict[str, dict[str, str]] = {
    "knowledge": {
        "title": "补语料：让本域有可检索内容",
        "detail": "缺口＝本域当前检索不到任何内容块。二选一：①在「知识库」区订阅已有库的源；"
                  "②若是新语料，先在 admin「语料库登记」建库/加源，再回来订阅。"
                  "验收：知识库区显示块数 > 0，全域名录该域的语料缺口消失。",
    },
    "ontology": {
        "title": "补本体：本域还没有已整理的知识单元",
        "detail": "缺口＝本域没有自己的知识单元（继承来的不算）。按模板声明的实体类型/关系类型"
                  "整理实体与关系，落库到本域路径。验收：本体区出现本域单元，缺口消失。",
    },
    "eval": {
        "title": "补评测标准：本域还没有可生效的 rubric",
        "detail": "缺口＝本域沿父链取不到任何 rubric。二选一：①继承父域标准（无需操作，订阅即生效）；"
                  "②新建本域标准；③偏离父域口径必须 fork 并写明差异。验收：评测标准区非空，缺口消失。",
    },
}


def dispatchable(rows: Iterable[dict], gap: str) -> list[dict]:
    """Rows missing ``gap``, with the reason a task would carry."""
    if gap not in GAP_TASKS:
        raise ValueError(f"unknown pillar {gap!r}; expected one of {sorted(GAP_TASKS)}")
    return [r for r in rows if gap in r["gaps"]]


def open_targets(conn: Any, *, domain_id: int, target_kind: str = "estate-gap") -> set[str]:
    """Pillars this domain already has an *open* task for."""
    rows = conn.execute(
        "SELECT target_key FROM authoring_tasks "
        "WHERE domain_id = %s AND target_kind = %s AND status IN ('pending','in_progress')",
        (domain_id, target_kind),
    ).fetchall()
    return {r["target_key"] for r in rows if r["target_key"]}


def plan(
    conn: Any,
    *,
    rows: Iterable[dict],
    gap: str,
    assignee: str,
) -> dict:
    """What a confirmation would do — computed without writing anything."""
    targets = dispatchable(rows, gap)
    will: list[dict] = []
    already: list[dict] = []
    for row in targets:
        domain = row["domain"]
        if gap in open_targets(conn, domain_id=domain["id"]):
            already.append(domain)
            continue
        will.append(domain)
    return {
        "gap": gap,
        "assignee": (assignee or "").strip(),
        "pillar": GAP_TASKS[gap],
        "will_create": will,
        "already_open": already,
    }


def dispatch(
    conn: Any,
    *,
    rows: Iterable[dict],
    gap: str,
    assignee: str,
    created_by: str,
) -> dict:
    """Create one task per domain still missing ``gap`` (idempotent per pillar)."""
    assignee = (assignee or "").strip()
    if not assignee:
        raise ValueError("assignee is required")
    planned = plan(conn, rows=rows, gap=gap, assignee=assignee)
    created: list[dict] = []
    for domain in planned["will_create"]:
        created.append(
            authoring.authoring_create_task(
                conn,
                domain_id=domain["id"],
                assignee=assignee,
                title=planned["pillar"]["title"],
                detail=planned["pillar"]["detail"],
                target_kind="estate-gap",
                target_key=gap,
                created_by=created_by,
            )
        )
    return {
        "gap": gap,
        "assignee": assignee,
        "created": created,
        "already_open": planned["already_open"],
    }


def rows_for_gap(conn: Any, *, domains: list[dict], gap: str) -> list[dict]:
    """Estate rows for the given domains (one network-free read per domain).

    ``estate.matrix`` is the single source of truth for what counts as a gap, so
    dispatch cannot disagree with the page that motivated it.
    """
    if gap not in GAP_TASKS:
        raise ValueError(f"unknown pillar {gap!r}; expected one of {sorted(GAP_TASKS)}")
    return estate.matrix(conn, domains=domains)
