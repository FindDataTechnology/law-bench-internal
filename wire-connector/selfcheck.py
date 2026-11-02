#!/usr/bin/env python3
"""Offline self-check for the wire-connector (internal repo has no pytest).

Run from anywhere with a bare python3 (no venv, no network):

    python3 wire-connector/selfcheck.py

Checks (all hermetic):
 1. package imports (client/sync/writeback load with stdlib only —
    ``requests``/``psycopg`` are lazy, so a missing package is reported as
    environment info, not a crash);
 2. public-kernel import through the LAW_BENCH_REPO wiring (VAAS precedent:
    internal → public only);
 3. pure promotion functions produce wire-shaped mirrors;
 4. client constructs with env/params and the no-credentials path raises an
    honest, actionable WireAuthError BEFORE any network touch;
 5. writeback stamp formatting carries tier/sensitivity/idempotency markers.

Prints 'OK <check>' per check; exits 1 with the failing check on any problem.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # .../law-bench-internal/wire-connector


def _fail(check: str, err: Exception) -> None:
    print(f"FAIL {check}: {type(err).__name__}: {err}")
    sys.exit(1)


def main() -> int:
    src = HERE / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    # 1. package imports (stdlib-only by design: lazy requests/psycopg)
    try:
        import wire_connector  # noqa: F401
        from wire_connector import client as _c, sync as _s, writeback as _w
    except Exception as e:  # noqa: BLE001
        _fail("wire_connector import", e)
    print("OK 1 wire_connector imports (client/sync/writeback)")

    # 2. public kernel through the cross-repo wiring
    try:
        promotion = _s.import_kernel()
        assert hasattr(promotion, "sync_graph")
        assert hasattr(promotion, "run_writeback")
        assert hasattr(promotion, "export_gold")
    except Exception as e:  # noqa: BLE001
        _fail("law-bench kernel import (set LAW_BENCH_REPO?)", e)
    print(f"OK 2 public kernel promotion module: {promotion.__file__}")

    # 3. pure mirror rendering (wire graph shape, fixture — no DB, no network)
    node = {
        "id": 1, "name": "Customer", "description": None,
        "pk_columns": ["cust_id"], "display_column": None, "column_notes": None,
        "dataset": {"id": "ds-1", "key": "customers", "name": "Customers",
                    "row_count": 120, "storage_tier": "hot"},
    }
    edge = {"id": 9, "from_entity_id": 2, "from_column": "cust_id",
            "to_entity_id": 1, "to_column": "cust_id", "kind": "n:1",
            "label": None, "junction_dataset_id": None,
            "junction_source_column": None, "junction_target_column": None}
    try:
        body = promotion.render_entity_body(node)
        assert "pk=[cust_id]" in body and "rows=120" in body, body
        rel = promotion.render_relation_body(edge)
        assert "(n:1)" in rel, rel
        assert promotion.entity_external_key(node) == "1"
        assert promotion.relation_external_key(edge) == "9"
    except Exception as e:  # noqa: BLE001
        _fail("mirror rendering", e)
    print("OK 3 wire-shaped node/edge render into unit bodies/keys")

    # 4. client: constructs; missing credentials fail honestly, pre-network
    try:
        c = _c.WireClient(base_url="http://wire.invalid", id_token="fake")
        assert c._headers()["Authorization"] == "Bearer fake"
        noauth = _c.WireClient(base_url="http://wire.invalid", id_token="")
        try:
            noauth.get_graph()
            raise AssertionError("expected WireAuthError with no token")
        except _c.WireAuthError as e:
            assert "WIRE_ID_TOKEN" in str(e), e
        naked = _c.WireClient(base_url="", id_token="x")
        try:
            naked.get_graph()
            raise AssertionError("expected WireClientError with no base")
        except _c.WireClientError as e:
            assert "WIRE_API_BASE" in str(e), e
    except Exception as e:  # noqa: BLE001
        _fail("client construction / no-credential error path", e)
    print("OK 4 client builds; no-cred paths raise actionable errors pre-network")

    # 5. writeback stamp markers (tier/sensitivity/idempotency on the payload)
    try:
        payload = {
            "kind": "entity", "external_key": "1", "tier": "gold",
            "sensitivity": "confidential", "idempotency_key": "wire/entity/1",
            "review": {"reviewer": "rev@x.com", "at": "2026-11-03T00:00:00+00:00"},
            "registry_fields": node,
        }
        stamp = _w.format_bench_stamp(payload)
        for marker in ("tier=gold", "sensitivity=confidential",
                       "idempotency_key=wire/entity/1", "reviewer=rev@x.com"):
            assert marker in stamp, (marker, stamp)
    except Exception as e:  # noqa: BLE001
        _fail("writeback stamp markers", e)
    print(f"OK 5 gold writeback stamp: {stamp}")

    # environment info (not pass/fail)
    try:
        import requests  # noqa: F401
        print("INFO live-call dependency 'requests' is installed")
    except ImportError:
        print("INFO 'requests' absent in this interpreter — live sync/writeback "
              "will report it honestly when run inside a venv that has it")
    print("INFO WIRE_API_BASE=%s WIRE_ID_TOKEN=%s BENCH_DATABASE_URL=%s LAW_BENCH_REPO=%s" % (
        os.environ.get("WIRE_API_BASE", "(unset)"),
        "set" if os.environ.get("WIRE_ID_TOKEN") else "(unset)",
        os.environ.get("BENCH_DATABASE_URL") or os.environ.get("database_url") or "(unset)",
        os.environ.get("LAW_BENCH_REPO", "(inferred sibling)"),
    ))
    print("\nALL SELFCHECKS PASSED (offline; no network touched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
