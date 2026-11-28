"""Machine asset transfer API (change add-bench-asset-portability).

A deployment-level consumer may export/import portable asset envelopes without
an admin identity. The credential is a registered `distribution_consumers` row
of kind `deployment-assets` — capability-limited to this API, so a compromised
cell gets asset transfer and nothing else (no members, publish, proposals,
confirmations, or any other admin surface).

Auth reuses the distribution token check (one implementation): `X-Consumer-Token`
-> sha256 -> registry row -> revoked/unknown are 403, missing is 401.

Domain scope: ruler/gold sets are per-domain, so when `domain_key` is supplied it
must be in the consumer's bound domains. Templates are instance-level and carry
no domain; the kind check alone gates them.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import DbConn, get_db
from ...bench import asset_transfer as bench_transfer
from .distribution import _authenticate_token

router = APIRouter(tags=["assets"])

#: External asset class -> the transfer kind it maps to.
_ASSET_TO_KIND = {
    "ontology": "ontology-template",
    "vocabulary": "vocabulary-release",
    "ruler": "ruler-set",
    "gold": "gold-set",
    "eval-suite": "eval-suite",
}

#: Asset classes that are per-domain and therefore need a bound domain.
_DOMAIN_ASSETS = ("ruler", "gold")


def _require_asset_consumer(request: Request, db: Any) -> dict:
    consumer = _authenticate_token(request, db)
    if consumer.get("kind") != "deployment-assets":
        raise HTTPException(
            status_code=403,
            detail="该凭据不具备资产转移能力（需 kind='deployment-assets'）",
        )
    return consumer


def _require_domain(consumer: dict, asset: str, domain_key: Optional[str]) -> None:
    if asset not in _DOMAIN_ASSETS:
        return
    if not domain_key:
        raise HTTPException(status_code=422, detail=f"{asset} 资产必须指定 domain_key")
    if domain_key not in (consumer.get("domains") or []):
        raise HTTPException(status_code=403, detail="该域不在凭据绑定范围")


@router.get("/api/v1/assets/{asset}/export", name="asset_api_export")
def export_asset(
    asset: str,
    name: str,
    request: Request,
    version: Optional[int] = None,
    domain_key: Optional[str] = None,
    db: DbConn = Depends(get_db),
) -> dict:
    consumer = _require_asset_consumer(request, db)
    kind = _ASSET_TO_KIND.get(asset)
    if kind is None:
        raise HTTPException(
            status_code=400,
            detail=f"未知资产类 {asset!r}；可用：{list(_ASSET_TO_KIND)}",
        )
    _require_domain(consumer, asset, domain_key)
    try:
        return bench_transfer.export_asset(
            db, kind=kind, name=name, version=version, domain_key=domain_key
        )
    except bench_transfer.TransferError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/api/v1/assets/import", name="asset_api_import")
def import_asset(
    payload: dict[str, Any],
    request: Request,
    db: DbConn = Depends(get_db),
) -> dict:
    consumer = _require_asset_consumer(request, db)
    raw = payload.get("envelope")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="envelope object is required")
    target = payload.get("target_domain_key")
    target = target if isinstance(target, str) else None
    asset = payload.get("asset")
    if isinstance(asset, str):
        _require_domain(consumer, asset, target)
    try:
        return bench_transfer.import_asset(
            db,
            raw=raw,
            actor=f"deployment:{consumer.get('name')}",
            target_domain_key=target,
        )
    except bench_transfer.TransferError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None