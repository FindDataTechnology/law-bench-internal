"""Knowledge-distribution web surface (change ``add-knowledge-distribution-contract``).

Two audiences live in this module:

1. **Machine pull API** — ``GET /api/v1/distribution/{domain_key}/ontology``
   serves versioned, immutable publication snapshots to registered consumers.
   It is deliberately Logto-free (spec: 拉取面 SHALL NOT 依赖 Logto 交互会话):
   the credential is the consumer's ``X-Consumer-Token`` header. Auth wiring
   (option (a) of the design's two options): the prefix
   ``/api/v1/distribution/`` is listed in ``_EXEMPT_PREFIXES``
   (``src/web/auth/deps.py``), so the app-level ``get_current_user`` resolves
   these paths to the anonymous sentinel — the same mechanism the invitation
   pages use — and THIS route performs its own token auth. The route never
   calls ``get_current_user`` / ``require_scope``. It is not mounted on
   ``public_app``.

   Three-state auth (spec ``knowledge-distribution`` 机器拉取面, exact):

   ==============  =====================================================
   missing header  401  ``缺少机器凭据：X-Consumer-Token 请求头``
   unknown token   403  ``令牌未登记``
   revoked token   403  ``令牌已吊销``        (distinct from unregistered)
   out-of-scope    403  ``该域不在绑定范围``  (domain content never leaked)
   no publication  404  ``该域尚无发布`` / ``该域无版本 v{N}``
   ==============  =====================================================

   The plaintext token is hashed on arrival and never logged or echoed; no
   error detail ever includes it.

   **Pull payload shape — the contract fd-wire codes against** (JSON,
   insertion order; the same tree is what ``format=yaml`` dumps):

   ::

       {
         "domain":              "<domain_key>",
         "template_name":       "<the domain's template name>",
         "template_version":    <manifest's template-version anchor>,
         "publication_version": <monotonic publication version N>,
         "digest":              "<sha256 of the canonical manifest>",
         "entities":            [ {kind, external_key, body, tier,
                                    sensitivity, attrs}, ... ],
         "relationships":       [ same item shape; attrs carries the
                                    structured "from"/"to" (+ from_key/
                                    to_key); external_key follows the
                                    authoring convention
                                    "{from_key}->{kind}:{to_key}" ],
         "changelog":           {diff vs the previous publication
                                    (added/removed/changed); the first
                                    version is {"initial": true, ...}}
       }

   ``entities``/``relationships`` are the frozen manifest's arrays verbatim
   (item fields per the kernel contract: kind/external_key/body/tier/
   sensitivity/attrs; ``sensitivity`` mirrors the KU's ``tags.sensitivity``,
   null when absent). ``?version=N`` pins a historical snapshot (byte-identical
   to its publish-time digest); default is the latest version. ``?format=json``
   (default) returns ``application/json``; ``?format=yaml`` returns
   ``application/x-yaml`` via ``yaml.safe_dump(..., allow_unicode=True,
   sort_keys=False)`` — PyYAML lives in the route layer only, the kernel stays
   dependency-free. Any other ``format`` is 422 naming the allowed values.

2. **Admin management** (Logto side): the consumer registry at
   ``/admin/distribution`` (``require_scope("admin")``) — register (issue
   token), revoke, rebind domains — and the per-domain publish action
   ``POST /admin/domains/{domain_key}/publish`` composed C1-style:
   ``require_scope("content:write")`` + ``require_domain_role("lead")``
   (admins bypass the domain check). The publications listing is rendered on
   the C1 domain detail page; its context is fetched in
   ``admin.py::admin_domain_detail`` (this module owns the publish POST).

Token discipline follows the C1 invitation pattern: ``secrets.token_urlsafe(32)``,
only ``hashlib.sha256(token).hexdigest()`` persisted via
``distribution.register_consumer(token_hash=...)``, plaintext shown exactly
once — in the creation flash.

The data layer is ``src/bench/distribution.py`` (kernel); this module stays a
thin web surface with the ``admin.py`` flash/redirect style.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Optional
from urllib.parse import quote

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..auth.deps import User, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...bench import distribution
from ...bench import workspaces

read_only_router = APIRouter(tags=["distribution"])
write_router = APIRouter(tags=["distribution"])


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``admin.py::_flash``.

    ``msg`` is a dotted i18n key resolved by ``base.html``'s ``tr`` helper;
    ``**interp`` values ride along as extra query params (the base template
    forwards ``name`` and ``detail`` into ``tr``).
    """
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    """Stable, readable operator stamp — same construction as ``admin.py``."""
    return user.email or user.name or user.sub


def _split_domains(raw: Any) -> list[str]:
    """Parse the comma-separated domain-keys form field (deduped, order kept)."""
    seen: list[str] = []
    for part in str(raw or "").split(","):
        key = part.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


# ------------------------------------------------------------ machine pull #
# Logto-free: this path prefix is exempted from the app-level get_current_user
# (see _EXEMPT_PREFIXES in src/web/auth/deps.py); the token check below IS the
# authentication for this surface.

_MISSING_TOKEN_DETAIL = "缺少机器凭据：X-Consumer-Token 请求头"
_UNREGISTERED_DETAIL = "令牌未登记"
_REVOKED_DETAIL = "令牌已吊销"
_OUT_OF_SCOPE_DETAIL = "该域不在绑定范围"
_NO_PUBLICATION_DETAIL = "该域尚无发布"

_ALLOWED_FORMATS = ("json", "yaml")


@read_only_router.get("/api/v1/distribution/{domain_key}/ontology", name="distribution_pull_ontology")
def pull_domain_ontology(
    domain_key: str,
    request: Request,
    version: Optional[int] = None,
    format: str = "json",
    db: DbConn = Depends(get_db),
):
    """Serve one publication snapshot to a registered consumer (see module docstring).

    Auth is the spec's three-state token check — no Logto identity involved.
    ``version=None`` fetches the latest publication; ``format`` is ``json``
    (default) or ``yaml``. The payload shape is documented in the module
    docstring — fd-wire codes against it.
    """
    fmt = (format or "").strip().lower()
    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail="invalid format: allowed values are 'json' or 'yaml'",
        )

    token = request.headers.get("x-consumer-token")
    if not token:
        raise HTTPException(status_code=401, detail=_MISSING_TOKEN_DETAIL)
    # Hash immediately; the plaintext never reaches a log, DB row, or error.
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    consumer = distribution.get_consumer_by_token_hash(db, token_hash=token_hash)
    if consumer is None:
        raise HTTPException(status_code=403, detail=_UNREGISTERED_DETAIL)
    if consumer.get("revoked_at") is not None:
        raise HTTPException(status_code=403, detail=_REVOKED_DETAIL)
    if domain_key not in (consumer.get("domains") or []):
        raise HTTPException(status_code=403, detail=_OUT_OF_SCOPE_DETAIL)

    publication = distribution.get_publication(db, domain_key=domain_key, version=version)
    if publication is None:
        detail = _NO_PUBLICATION_DETAIL if version is None else f"该域无版本 v{version}"
        raise HTTPException(status_code=404, detail=detail)

    manifest = publication.get("manifest") or {}
    domain_row = workspaces.get_domain(db, domain_key=domain_key)

    # C5 pull footprint: record the successful pull (append-only; the consumer
    # row itself is never updated). Only a pull that actually resolved a
    # publication reaches this line — a rejected credential or a 404 above
    # never does, so the trail never claims a pull that did not happen.
    # Best effort: a footprint write must never turn a served snapshot into a
    # 500, so a failure here is swallowed by design (the payload is already
    # computed and remains correct).
    try:
        db.execute(
            "INSERT INTO distribution_pull_events (consumer_id, domain_key, version) "
            "VALUES (%s, %s, %s)",
            (consumer["id"], domain_key, publication["version"]),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - see the comment above
        pass

    payload = {
        "domain": manifest.get("domain") or domain_key,
        "template_name": manifest.get("template_name")
        or (domain_row or {}).get("template_name"),
        "template_version": manifest.get("template_version"),
        "publication_version": publication["version"],
        "digest": publication["digest"],
        "entities": manifest.get("entities") or [],
        "relationships": manifest.get("relationships") or [],
        "changelog": publication.get("changelog"),
    }
    if fmt == "yaml":
        body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        return Response(content=body, media_type="application/x-yaml")
    return JSONResponse(content=payload)


# --------------------------------------------------------- consumer registry #
# Platform-admin exclusive: consumers are the machine counterpart of invited
# members — admission, binding and revocation are all admin-scope operations.


@read_only_router.get(
    "/admin/distribution", include_in_schema=False, name="admin_distribution",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_distribution(request: Request, db: DbConn = Depends(get_db)):
    """Consumer registry: binding, status, token issue/revoke/rebind forms."""
    return _templates.TemplateResponse(
        request,
        "admin_distribution.html",
        {"consumers": distribution.list_consumers(db)},
    )


@write_router.post(
    "/admin/distribution/consumers", include_in_schema=False,
    name="admin_consumer_register",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_register(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Register a consumer and mint its machine token — plaintext shown once.

    Only ``sha256(token)`` is persisted (``register_consumer(token_hash=...)``);
    the plaintext rides the creation flash, the single time it exists.
    """
    form = await request.form()
    name = (form.get("name") or "").strip()
    domains = _split_domains(form.get("domains"))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        distribution.register_consumer(
            db, name=name, domains=domains, token_hash=token_hash,
            created_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(
            "/admin/distribution", "flash.consumer_register_failed",
            err=True, detail=str(exc),
        )
    return _flash("/admin/distribution", "flash.consumer_registered", name=name, detail=token)


@write_router.post(
    "/admin/distribution/consumers/{name}/revoke", include_in_schema=False,
    name="admin_consumer_revoke",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_revoke(
    request: Request,
    name: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Revoke a consumer's token — pulls fail immediately (spec scenario)."""
    try:
        distribution.revoke_consumer(db, name=name)
    except ValueError as exc:
        return _flash("/admin/distribution", "flash.consumer_revoke_failed", err=True, detail=str(exc))
    return _flash("/admin/distribution", "flash.consumer_revoked", name=name)


@write_router.post(
    "/admin/distribution/consumers/{name}/domains", include_in_schema=False,
    name="admin_consumer_domains",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_domains(
    request: Request,
    name: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Replace a consumer's bound-domain set (binding change = whole-set swap)."""
    form = await request.form()
    domains = _split_domains(form.get("domains"))
    try:
        distribution.set_consumer_domains(db, name=name, domains=domains)
    except ValueError as exc:
        return _flash("/admin/distribution", "flash.consumer_domains_failed", err=True, detail=str(exc))
    return _flash(
        "/admin/distribution", "flash.consumer_domains_set",
        name=name, detail=", ".join(domains),
    )


# ----------------------------------------------------------------- publish #
# C1's two-gate composition: platform scope (content:write) then domain role
# (lead; admins bypass). The kernel enforces the data-side rules (unknown
# domain, empty domain) as ValueError; the route maps them to a failure flash.


@write_router.post(
    "/admin/domains/{domain_key}/publish", include_in_schema=False,
    name="admin_domain_publish",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_domain_publish(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Freeze the domain's content into an immutable publication snapshot.

    Idempotency: ``publish_domain`` returns the existing row when the computed
    digest already exists for the domain — the flash distinguishes that case
    (no new snapshot) from a genuinely new version by checking the digests
    known before the call.
    """
    back = f"/admin/domains/{quote(domain_key)}"
    try:
        known = {
            p.get("digest")
            for p in distribution.list_publications(db, domain_key=domain_key)
        }
        publication = distribution.publish_domain(
            db, domain_key=domain_key, published_by=_operator_of(user)
        )
    except ValueError as exc:
        return _flash(back, "flash.publish_failed", err=True, detail=str(exc))
    if publication.get("digest") in known:
        return _flash(
            back, "flash.published_idempotent", detail=f"v{publication['version']}"
        )
    return _flash(
        back, "flash.published",
        detail=f"v{publication['version']} · digest {str(publication.get('digest'))[:12]}",
    )


router = APIRouter(tags=["distribution"])
router.include_router(read_only_router)
router.include_router(write_router)
