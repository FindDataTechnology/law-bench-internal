"""Domain-first console: the platform's front door and per-domain areas (C5).

Change ``add-domain-first-workbench``. This module is the human face of the
domain kernel built by C1–C4; it adds no ontology semantics of its own:

- ``/d`` — **my domains**. The authenticated landing point: one row per active
  membership, my own recency first. Replaces the old ``/`` → ``/rubrics``
  redirect, which dropped everyone into the legal rubric list regardless of
  which domain they actually work in.
- ``/d/{domain_key}`` — **overview**: four real counts (units, latest release,
  pending proposals, my tasks), the task panel (claim/complete/cancel still post
  to the existing workbench routes), the anchored vocabulary, recent changes.
- ``/d/{domain_key}/ontology`` — the four-layer ledger (declaration, curation,
  publication, consumption) plus the declaration-vs-corpus reconciliation. Pure
  read: the page is a projection of ``src.bench.ledger`` and never computes a
  digest of its own, so it can never disagree with the machine pull surface.
- ``/d/{domain_key}/inbox`` — the proposal inbox: drafts land here, a lead
  confirms them through the kernel's single write path, and rejections return
  the draft without auto-retry.
- ``/d/{domain_key}/publish`` — release history, consumers, pull footprints.
- ``/d/{domain_key}/bench`` — the domain's evaluation-asset shelf (a directory;
  it never changes an asset).
- ``/d/{domain_key}/settings`` — this domain's members and invitations.

Authorization is deliberately the same composition as ``authoring.py``: platform
scope first (Logto only), then the domain role (``domain_members`` only), then
the area's own minimum role. Every route names its path param ``domain_key``
because ``require_domain_role`` reads exactly that param. Navigation hiding is
usability; these dependencies are the enforcement.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import User, get_current_user, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..domain_context import (
    capability,
    console_context,
    is_platform_admin,
    resolve_domain,
)
from ..templating import templates as _templates
from .authoring import sorted_tasks
from ...bench import authoring as bench_authoring
from ...bench import distribution as bench_distribution
from ...bench import domain_assets as bench_domain_assets
# Importing the legal pack registers its asset kinds with the kernel catalog.
# The kernel stays domain-free; this app IS the legal deployment, so the pack
# import belongs at the app's edge (this module), never inside src/bench.
from packs.legal import asset_catalog as _legal_asset_catalog  # noqa: F401
from ...bench import ledger as bench_ledger
from ...bench import domain_rubrics
from ...bench import estate
from ...bench import templates
from ...bench import libraries as library_store
from ...bench import proposals as bench_proposals
from ...search import library_index
from ...bench import templates as bench_templates
from ...bench import workspaces

read_only_router = APIRouter(tags=["console"])
write_router = APIRouter(tags=["console"])

# Two-gate composition (platform scope ▶ domain role). ``viewer`` does not
# exist in the kernel's role vocabulary — the read floor is ``annotator``
# (审核标注员), which is read-only in the authoring surface too.
_READ_GATES = [
    Depends(require_scope("content:read")),
    Depends(require_domain_role("annotator")),
]
_WRITE_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("expert")),
]
_LEAD_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("lead")),
]


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``admin.py::_flash``."""
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    return user.email or user.name or user.sub


def _anchored_schema(conn: DbConn, domain: dict) -> dict:
    """The exact template-version schema the domain is anchored to."""
    tmpl = bench_templates.get_template_by_id(conn, template_id=domain["template_id"])
    return (tmpl or {}).get("schema") or {}


# ------------------------------------------------------------------ landing #


@read_only_router.get(
    "/d", include_in_schema=False, name="console_domain_list",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_domain_list(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """My domains — the authenticated landing point.

    A platform admin with no membership sees the empty state plus the platform
    gate: the page never invents a domain, and never lists a domain the caller
    cannot enter.
    """
    domains = workspaces.list_member_domains(db, user_id=user.sub)
    if not domains and is_platform_admin(user):
        # A platform admin's visible range is every domain, not just the ones
        # they hold a membership in: otherwise the estate console (the page that
        # answers "what is missing where") is empty for the only role that can
        # act on it. Role is reported as 'admin' — an honest label for a bypass,
        # not a fabricated membership row.
        domains = [
            {**d, "role": "admin", "last_opened_at": None}
            for d in workspaces.list_domains(db)
        ]
    # Estate view (add-domain-tree-and-shared-libraries §4.2): the landing page
    # used to be "the domains I belong to". With many sub-domains the operator's
    # real question is "what is missing where", so every row carries its four
    # pillar summaries and its gaps.
    gap = (request.query_params.get("gap") or "").strip() or None
    rows = estate.filter_rows(estate.matrix(db, domains=domains), gap)
    return _templates.TemplateResponse(
        request,
        "domain_list.html",
        {
            "domains": domains,
            "rows": rows,
            "gap": gap,
            "pillars": estate.PILLARS,
            "gap_counts": {
                key: len([r for r in estate.matrix(db, domains=domains) if key in r["gaps"]])
                for key in ("ontology", "knowledge", "eval")
            },
            "platform_admin": is_platform_admin(user),
        },
    )


@read_only_router.get(
    "/d/switch", include_in_schema=False, name="console_switch",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_switch(
    to: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Server-validated domain switch (the switcher's GET target).

    The form value is a *candidate*: membership is re-checked here, so a
    hand-edited value cannot reach a domain the caller is not a member of. A
    platform admin may switch anywhere (the same bypass the route gates use).
    """
    target = workspaces.get_domain(db, domain_key=to)
    if target is None:
        raise HTTPException(status_code=404, detail=f"domain {to!r} not found")
    if not is_platform_admin(user):
        role = workspaces.get_active_role(
            db, domain_id=target["id"], user_id=user.sub
        )
        if role is None:
            raise HTTPException(status_code=403, detail="无该域权限")
    return RedirectResponse(
        f"/d/{quote(target['key'], safe='')}", status_code=303
    )


# ----------------------------------------------------------------- overview #


# ------------------------------------------------------------ new domain #


@read_only_router.get(
    "/d/new", include_in_schema=False, name="console_new_domain",
    dependencies=[Depends(require_scope("admin"))],
)
def console_new_domain(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The sub-domain wizard: pick a parent, preview inheritance, then create.

    Creating a domain is an **admin** action (the same gate as ``/admin``): the
    wizard exists to make it a five-minute job, not to widen who may do it.
    """
    parents = workspaces.list_domains(db)
    parent_key = (request.query_params.get("parent") or "").strip() or None
    preview = None
    if parent_key:
        parent = workspaces.get_domain(db, domain_key=parent_key)
        if parent is not None:
            parent_template = templates.get_template_by_id(
                db, template_id=parent["template_id"]
            )
            try:
                scope = library_index.explain_scope(db, domain_path=parent["path"])
            except ValueError as exc:
                scope = {"libraries": [], "error": str(exc)}
            preview = {
                "parent": parent,
                "template": parent_template,
                "scope": scope,
            }
    return _templates.TemplateResponse(
        request,
        "domain_new.html",
        {
            "parents": parents,
            "parent_key": parent_key,
            "preview": preview,
            "libraries": library_store.list_libraries(db),
        },
    )


@write_router.post(
    "/d/new", include_in_schema=False, name="console_new_domain_create",
    dependencies=[Depends(require_scope("admin"))],
)
async def console_new_domain_create(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create the sub-domain, subscribe it to the chosen sources, land on it.

    Subscriptions are applied **after** creation and are narrowed against the
    parent: a wizard selection that would widen the parent's scope is refused by
    ``effective_sources`` and rolled back, so the wizard cannot produce a domain
    whose scope the retriever would then reject.
    """
    form = await request.form()
    key = (form.get("key") or "").strip()
    name = (form.get("name") or "").strip()
    parent_key = (form.get("parent_key") or "").strip() or None
    selected = form.getlist("source")  # "library_key:source_key"
    try:
        created = workspaces.instantiate_domain(
            db,
            key=key,
            name=name,
            template_name=(form.get("template_name") or "").strip(),
            template_version=(
                int(form.get("template_version"))
                if (form.get("template_version") or "").strip()
                else None
            ),
            created_by=_operator_of(user),
            parent_key=parent_key,
        )
        if selected:
            by_lib: dict[str, list[str]] = {}
            for token in selected:
                lib, _, src = token.partition(":")
                if lib and src:
                    by_lib.setdefault(lib, []).append(src)
            for lib_key, sources in by_lib.items():
                library_store.subscribe(
                    db,
                    domain_id=created["id"],
                    library_key=lib_key,
                    created_by=_operator_of(user),
                    source_filter=sources,
                )
            # Prove the result is a legal scope before declaring success: this is
            # the same resolver retrieval uses, so a bad selection fails here.
            library_index.explain_scope(db, domain_path=created["path"])
    except ValueError as exc:
        db.rollback()
        return _flash(
            f"/d/new?parent={quote(parent_key or '', safe='')}",
            "console.flash.domain_create_failed",
            err=True,
            detail=str(exc),
        )
    return _flash(
        f"/d/{quote(created['key'], safe='')}", "console.flash.domain_created",
        name=created["name"],
    )


@read_only_router.get(
    "/d/{domain_key}", include_in_schema=False, name="console_overview",
    dependencies=_READ_GATES,
)
def console_overview(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Domain overview: four real counts, my tasks, vocabulary, recent changes."""
    domain = resolve_domain(db, domain_key)
    schema = _anchored_schema(db, domain)
    ctx = console_context(db, domain, user, touch=True)
    curation = bench_ledger.curation_layer(db, domain=domain, recent_limit=5)
    publication = bench_ledger.publication_layer(db, domain=domain, history_limit=1)
    return _templates.TemplateResponse(
        request,
        "domain_console_overview.html",
        {
            **ctx,
            "entity_types": list(schema.get("entity_types") or []),
            "relationship_kinds": list(schema.get("relationship_kinds") or []),
            "curation": curation,
            "publication": publication,
            "pending_count": bench_proposals.count_pending(db, domain_key=domain_key),
            "my_tasks": sorted_tasks(
                bench_authoring.authoring_list_tasks(
                    db, domain_id=domain["id"], assignee=user.sub
                )
            ),
            "recent_events": curation.get("recent_events") or [],
        },
    )


# ----------------------------------------------------------------- ontology #


@read_only_router.get(
    "/d/{domain_key}/ontology", include_in_schema=False, name="console_ontology",
    dependencies=_READ_GATES,
)
def console_ontology(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The four-layer ontology ledger plus the consistency reconciliation."""
    domain = resolve_domain(db, domain_key)
    ledger = bench_ledger.ledger(db, domain=domain)
    return _templates.TemplateResponse(
        request,
        "domain_console_ontology.html",
        {
            **console_context(db, domain, user),
            **ledger,
        },
    )


# -------------------------------------------------------------------- inbox #


@read_only_router.get(
    "/d/{domain_key}/inbox", include_in_schema=False, name="console_inbox",
    dependencies=_READ_GATES,
)
def console_inbox(
    request: Request,
    domain_key: str,
    state: Optional[str] = None,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The domain's proposal inbox, optionally filtered by state."""
    domain = resolve_domain(db, domain_key)
    try:
        proposals = bench_proposals.list_proposals(
            db, domain_key=domain_key, state=state
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _templates.TemplateResponse(
        request,
        "domain_console_inbox.html",
        {
            **console_context(db, domain, user),
            "proposals": proposals,
            "state_filter": state,
        },
    )


@write_router.post(
    "/d/{domain_key}/inbox/{proposal_id}/confirm", include_in_schema=False,
    name="console_inbox_confirm", dependencies=_LEAD_GATES,
)
def console_inbox_confirm(
    domain_key: str,
    proposal_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Confirm one proposal into the ontology through the kernel write path.

    The submitter may not confirm their own proposal (the kernel enforces it;
    this route passes the platform-admin flag so an administrator's override is
    recorded explicitly in the proposal's event note).
    """
    back = f"/d/{quote(domain_key, safe='')}/inbox"
    try:
        bench_proposals.confirm(
            db,
            domain_key=domain_key,
            proposal_id=proposal_id,
            actor=_operator_of(user),
            admin_override=is_platform_admin(user),
        )
    except PermissionError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    except ValueError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.proposal_confirmed")


@write_router.post(
    "/d/{domain_key}/inbox/{proposal_id}/reject", include_in_schema=False,
    name="console_inbox_reject", dependencies=_LEAD_GATES,
)
async def console_inbox_reject(
    request: Request,
    domain_key: str,
    proposal_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Reject one proposal; a reason is required."""
    form = await request.form()
    note = str(form.get("note") or "").strip()
    back = f"/d/{quote(domain_key, safe='')}/inbox"
    try:
        bench_proposals.reject(
            db,
            domain_key=domain_key,
            proposal_id=proposal_id,
            actor=_operator_of(user),
            note=note,
        )
    except ValueError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.proposal_rejected")


# ------------------------------------------------------------------ publish #


@read_only_router.get(
    "/d/{domain_key}/publish", include_in_schema=False, name="console_publish",
    dependencies=_READ_GATES,
)
def console_publish(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Release history, registered consumers and their pull footprints."""
    domain = resolve_domain(db, domain_key)
    return _templates.TemplateResponse(
        request,
        "domain_console_publish.html",
        {
            **console_context(db, domain, user),
            "publication": bench_ledger.publication_layer(db, domain=domain),
            "consumption": bench_ledger.consumption_layer(db, domain=domain),
        },
    )


@write_router.post(
    "/d/{domain_key}/publish", include_in_schema=False, name="console_publish_action",
    dependencies=_LEAD_GATES,
)
def console_publish_action(
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Freeze the next immutable version through the existing publish function.

    No second publication implementation: this is ``distribution.publish_domain``
    (idempotent on an unchanged digest), so the ledger, the pull surface and the
    admin release page can only ever agree on what v{N} is.
    """
    back = f"/d/{quote(domain_key, safe='')}/publish"
    try:
        publication = bench_distribution.publish_domain(
            db, domain_key=domain_key, published_by=_operator_of(user)
        )
    except ValueError as exc:
        return _flash(back, "console.flash.publish_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.published", version=publication["version"])


# -------------------------------------------------------------------- bench #


@read_only_router.get(
    "/d/{domain_key}/eval-runs", include_in_schema=False, name="console_eval_runs",
    dependencies=_READ_GATES,
)
def console_eval_runs(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The domain's evaluation-asset shelf plus the unassigned pool.

    Renamed from ``bench`` when the console grew evaluation *standards* as their
    own area (add-domain-tree-and-shared-libraries §4): the assets/runs view is
    what ``bench`` always showed, and the old URL now 302s here.
    """
    domain = resolve_domain(db, domain_key)
    groups = bench_domain_assets.list_for_domain(db, domain_key=domain_key)
    has_orphans = any(
        not item["exists"]
        for group in groups["groups"]
        for item in group["items"]
    )
    return _templates.TemplateResponse(
        request,
        "domain_console_bench.html",
        {
            **console_context(db, domain, user),
            "groups": groups,
            "unassigned": bench_domain_assets.list_unassigned(
                db, domain_key=domain_key
            ),
            "has_orphans": has_orphans,
        },
    )


@read_only_router.get(
    "/d/{domain_key}/bench", include_in_schema=False, name="console_bench_legacy",
)
def console_bench_legacy(domain_key: str):
    """Legacy ``bench`` URL → the renamed evaluation-runs area (302, never 404)."""
    return RedirectResponse(
        url=f"/d/{quote(domain_key, safe='')}/eval-runs", status_code=302
    )


# --------------------------------------------------------------- knowledge #


@read_only_router.get(
    "/d/{domain_key}/knowledge", include_in_schema=False, name="console_knowledge",
    dependencies=_READ_GATES,
)
def console_knowledge(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The corpus this domain can actually retrieve from, with its provenance.

    The scope is resolved by the same function retrieval uses
    (``library_index.explain_scope``), so the page cannot claim a range the
    search would not honour.
    """
    domain = resolve_domain(db, domain_key)
    try:
        scope = library_index.explain_scope(db, domain_path=domain["path"])
        # How much content each library actually holds for this domain, counted
        # through the same resolver the search uses (an external library is
        # counted in its own store). "36 万块" has to be measured here — a
        # source count that happens to look green is exactly what this page
        # exists to prevent.
        counted = library_index.count_scope(db, domain_path=domain["path"])
        for lib in scope["libraries"]:
            lib["chunks"] = counted["by_library"].get(lib["library_key"])
        if counted["errors"]:
            scope["count_error"] = "; ".join(counted["errors"])
    except ValueError as exc:  # a stored subscription that would widen scope
        scope = {"domain_path": domain["path"], "libraries": [], "error": str(exc)}
    return _templates.TemplateResponse(
        request,
        "domain_console_knowledge.html",
        {
            **console_context(db, domain, user),
            "scope": scope,
            "libraries": library_store.list_libraries(db),
        },
    )


# --------------------------------------------------------- eval standards #


@read_only_router.get(
    "/d/{domain_key}/eval-standards", include_in_schema=False,
    name="console_eval_standards", dependencies=_READ_GATES,
)
def console_eval_standards(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Own rubrics plus the ones inherited by reference from ancestors."""
    domain = resolve_domain(db, domain_key)
    standards = domain_rubrics.effective_rubrics(db, domain_path=domain["path"])
    return _templates.TemplateResponse(
        request,
        "domain_console_eval_standards.html",
        {
            **console_context(db, domain, user),
            "standards": standards,
            "own": [s for s in standards if s["origin"] == "own"],
            "inherited": [s for s in standards if s["origin"] == "inherited"],
        },
    )


@write_router.post(
    "/d/{domain_key}/bench/assign", include_in_schema=False,
    name="console_bench_assign", dependencies=_LEAD_GATES,
)
async def console_bench_assign(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Add one asset to this domain's shelf (a directory entry, never a copy)."""
    form = await request.form()
    back = f"/d/{quote(domain_key, safe='')}/bench"
    try:
        bench_domain_assets.assign(
            db,
            domain_key=domain_key,
            asset_kind=str(form.get("asset_kind") or ""),
            asset_key=str(form.get("asset_key") or ""),
            added_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "console.flash.asset_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.asset_assigned")


@write_router.post(
    "/d/{domain_key}/bench/unassign", include_in_schema=False,
    name="console_bench_unassign", dependencies=_LEAD_GATES,
)
async def console_bench_unassign(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Remove one directory entry; the asset itself is untouched."""
    form = await request.form()
    back = f"/d/{quote(domain_key, safe='')}/bench"
    bench_domain_assets.unassign(
        db,
        domain_key=domain_key,
        asset_kind=str(form.get("asset_kind") or ""),
        asset_key=str(form.get("asset_key") or ""),
    )
    return _flash(back, "console.flash.asset_unassigned")


@write_router.post(
    "/d/{domain_key}/bench/purge", include_in_schema=False,
    name="console_bench_purge", dependencies=_LEAD_GATES,
)
def console_bench_purge(
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Drop directory rows whose asset no longer exists (orphans only)."""
    back = f"/d/{quote(domain_key, safe='')}/bench"
    try:
        bench_domain_assets.purge_orphans(db, domain_key=domain_key)
    except ValueError as exc:
        return _flash(back, "console.flash.asset_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.asset_unassigned")


# ----------------------------------------------------------------- settings #


@read_only_router.get(
    "/d/{domain_key}/settings", include_in_schema=False, name="console_settings",
    dependencies=_LEAD_GATES,
)
def console_settings(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This domain's members and invitations (platform-level work stays in /admin)."""
    domain = resolve_domain(db, domain_key)
    ctx = console_context(db, domain, user)
    return _templates.TemplateResponse(
        request,
        "domain_console_settings.html",
        {
            **ctx,
            "members": workspaces.list_members(db, domain_id=domain["id"]),
            "invitations": workspaces.list_invitations(db, domain_id=domain["id"]),
        },
    )


# ------------------------------------------------- internal submit surface #
# The platform's own automation (the ontology fleet) and experts submit drafts
# here instead of pushing them into a consumer's approval queue. Platform
# self-closure is the point: production lands in the domain that owns it.


@write_router.post(
    "/api/d/{domain_key}/proposals", include_in_schema=False,
    name="console_proposal_submit", dependencies=_WRITE_GATES,
)
async def console_proposal_submit(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit one draft into the domain's inbox (idempotent on a pending key)."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be a JSON object")
    try:
        proposal, created = bench_proposals.submit(
            db,
            domain_key=domain_key,
            source=str(payload.get("source") or "").strip(),
            kind=str(payload.get("kind") or "").strip(),
            external_key=str(payload.get("external_key") or "").strip(),
            body=str(payload.get("body") or "").strip(),
            evidence=payload.get("evidence"),
            impact=str(payload.get("impact") or ""),
            submitted_by=str(payload.get("submitted_by") or "").strip()
            or _operator_of(user),
            with_created=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": proposal["id"],
        "state": proposal["state"],
        "external_key": proposal["external_key"],
        "evidence_digest": proposal["evidence_digest"],
        # False = idempotent hit on the existing pending row. The submitting
        # fleet reports 新增 vs 幂等命中 from this flag; without it both look
        # identical and the round's count cannot be trusted.
        "created": created,
    }
