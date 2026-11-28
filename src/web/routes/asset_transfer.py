"""Portable asset transfer endpoints (change add-bench-asset-portability).

JSON, admin-scoped, and disabled unless ``BENCH_ASSET_PORTABILITY`` is on. Lives
under ``/api/admin/assets`` — NOT ``/api/v1/`` — because that prefix is the
Logto-free machine pull surface; a transfer is an administrator action and must
run through the normal identity gate.

Export is read-only. Import verifies the envelope whole (digest + side files)
before any write; only a successful import leaves an audit row.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..auth.deps import User, require_scope
from ..deps import DbConn, get_db
from ...bench import asset_transfer as bench_transfer

router = APIRouter(tags=["asset-transfer"])


def _operator_of(user: User) -> str:
    return user.email or user.name or user.sub


def _refusal(exc: bench_transfer.TransferError) -> HTTPException:
    message = str(exc)
    # A disabled surface is a deployment state, not a bad request.
    status = 503 if "not enabled" in message else 400
    return HTTPException(status_code=status, detail=message)


@router.get("/api/admin/assets/export")
def export_asset(
    kind: str,
    name: str,
    version: Optional[int] = None,
    domain_key: Optional[str] = None,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
) -> dict[str, Any]:
    """Export one asset version as a portable envelope (read-only)."""
    try:
        return bench_transfer.export_asset(
            db, kind=kind, name=name, version=version, domain_key=domain_key
        )
    except bench_transfer.TransferError as exc:
        raise _refusal(exc) from None


@router.post("/api/admin/assets/import")
def import_asset(
    payload: dict[str, Any],
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
) -> dict[str, Any]:
    """Import one envelope. Accepted whole or rejected whole."""
    raw = payload.get("envelope")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="envelope object is required")
    target = payload.get("target_domain_key")
    try:
        return bench_transfer.import_asset(
            db,
            raw=raw,
            actor=_operator_of(user),
            target_domain_key=target if isinstance(target, str) else None,
        )
    except bench_transfer.TransferError as exc:
        raise _refusal(exc) from None
