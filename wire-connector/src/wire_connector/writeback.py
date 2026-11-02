"""Gold → wire writeback through the REAL writable surface (no pretense).

What fd-wire's entity API actually accepts (verified on-disk 2026-11-03):

- ``PUT /api/v1/entities/{id}`` — full replacement of ``EntityCreateIn``:
  ``{name, dataset_id, pk_columns, description, display_column,
  column_notes}``. No PATCH, no ``tier``, no ``sensitivity`` field anywhere.
- relationships: POST (declare) / DELETE only — **no update surface**.

So the contract's "回写载荷含 sensitivity/tier 标记" cannot be satisfied by a
first-class field on wire today. Until wire adds one (README 'contract gaps'),
this module writes the promotion stamp into the metadata bag wire DOES accept:
``column_notes["_bench"]`` (an underscore-prefixed key — column names in wire
come from dataset snapshots, so ``_bench`` cannot collide with a real column).
The stamp is machine-readable and carries the tier/sensitivity/reviewer/
idempotency key, so wire's ACL/fleet consumers can parse it today and be
upgraded to a first-class field later without touching bench.

Idempotency: the kernel (``run_writeback`` in the public promotion machine)
skips units already marked written-back — the wire key ``wire/<kind>/<id>`` is
the idempotency key, no double-push, no duplicate rows upstream.

Failure posture (contract: 回写失败不误标「已回写」): any exception from
``client.update_entity`` (transport, 401, 409, 422…) propagates up; the kernel
records the unit as NOT written back, continues with the rest of the batch,
and reports the error per unit. Relations raise immediately ("no writable
surface") — honest failure, never a fake success.
"""

from __future__ import annotations

from typing import Any

from .client import WireClient, WireClientError

#: reserved key in wire's column_notes metadata bag carrying the bench stamp
BENCH_NOTE_KEY = "_bench"


def format_bench_stamp(payload: dict) -> str:
    """Machine-readable one-string stamp (parsed by wire-side consumers)."""
    review = payload.get("review") or {}
    parts = [
        "platform=knowledge-bench",
        f"tier={payload.get('tier', 'gold')}",
        f"sensitivity={payload.get('sensitivity', 'internal')}",
        f"idempotency_key={payload.get('idempotency_key', '')}",
    ]
    if review.get("reviewer"):
        parts.append(f"reviewer={review['reviewer']}")
    if review.get("at"):
        parts.append(f"review_at={review['at']}")
    return "; ".join(parts)


class WireWriteback:
    """``writeback_fn`` for the kernel's ``run_writeback``.

    Usage::

        from src.bench import promotion
        from wire_connector.writeback import WireWriteback
        promotion.run_writeback(conn, "wire", WireWriteback(client))
    """

    def __init__(self, client: Any = None) -> None:
        self.client = client or WireClient()

    def __call__(self, payload: dict) -> dict:
        kind = payload.get("kind")
        if kind == "entity":
            return self._write_entity(payload)
        if kind == "relation":
            raise WireClientError(
                "wire has no writable surface for relations (POST/DELETE only"
                ", no tier/sensitivity/update endpoint) — see "
                "wire-connector/README.md 'contract gaps'"
            )
        raise WireClientError(f"unknown payload kind {kind!r}")

    def _write_entity(self, payload: dict) -> dict:
        node = payload.get("registry_fields") or {}
        # rebuild the full-replacement body from the mirrored snapshot
        # (wire identity master semantics: PUT revalidates the whole row)
        ds = node.get("dataset") or {}
        dataset_id = ds.get("id")
        if not dataset_id or not node.get("pk_columns") or not node.get("name"):
            raise WireClientError(
                "mirrored node snapshot lacks name/dataset.id/pk_columns — "
                "refusing to write a half-replacement; re-sync first"
            )
        notes = dict(node.get("column_notes") or {})
        notes[BENCH_NOTE_KEY] = format_bench_stamp(payload)
        resp = self.client.update_entity(
            int(payload["external_key"]),
            name=node["name"],
            dataset_id=str(dataset_id),
            pk_columns=list(node["pk_columns"]),
            description=node.get("description"),
            display_column=node.get("display_column"),
            column_notes=notes,
        )
        receipt = {
            "endpoint": f"PUT /api/v1/entities/{payload['external_key']}",
            "wire_updated_at": (resp or {}).get("updated_at"),
            "stamp_key": BENCH_NOTE_KEY,
        }
        # carry the idempotency key in the receipt for full traceability
        receipt["idempotency_key"] = payload.get("idempotency_key")
        return receipt


def run_writeback(conn: Any, namespace: str = "wire", client: Any = None) -> dict:
    """Convenience: kernel run_writeback with the real wire channel."""
    from .sync import import_kernel

    promotion_mod = import_kernel()
    return promotion_mod.run_writeback(conn, namespace, WireWriteback(client))


__all__ = ["BENCH_NOTE_KEY", "WireWriteback", "format_bench_stamp", "run_writeback"]
