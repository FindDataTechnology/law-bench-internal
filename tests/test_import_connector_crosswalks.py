"""Connector evidence → crosswalk units (change add-crosswalk-seam, task 3.3).

The import is deliberately literal: `connectivity` is copied verbatim from the
ERP file, and **no confidence is invented**. That is the whole point of the
three-state discipline — the file says how far each integration has been
verified, not how sure anyone is that the mapping is right. Synthesising a
confidence would count as reviewed something nobody reviewed, and the coverage
ratio would then be inflated by exactly the rows still awaiting review.

**One unit per integration** — the crosswalk. An earlier version also created an
`external_system:<provider>` entity, on the theory that "a crosswalk must point
at a real endpoint". That rule is about the **near** end (`organization:<provider>`),
not the peer: a peer is an opaque `external_id` triple, and manufacturing units
for it forced every template to declare an `external_system` type for the sake of
one write path (found 2026-11-19 — `enterprise-base` does not declare it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import import_connector_crosswalks as importer  # noqa: E402


def status(*integrations) -> dict:
    return {"integrations": list(integrations)}


def integration(provider: str, template: str, **states) -> dict:
    base = {
        "provider": provider,
        "template": template,
        "external_system": provider.title(),
        "state": "not_connected",
        "states": {
            "catalog": {"ok": states.get("catalog", False), "evidence": "c.json"},
            "executor_tests": {"ok": states.get("executor_tests", False), "evidence": "t.ts"},
            "live": {"ok": states.get("live", False), "evidence": None},
        },
    }
    return base


# ------------------------------------------------------------------- plans


def test_one_crosswalk_per_template_and_provider():
    """The same provider twice (two verticals) is two distinct bindings."""
    rows = importer.plans(
        status(integration("wechatpay", "restaurant-chain"),
               integration("wechatpay", "supply-chain")),
        target="organization",
    )
    assert len(rows) == 2, "keying by provider alone would collapse them"


def test_duplicate_provider_within_one_template_is_deduped():
    rows = importer.plans(
        status(integration("kingdee", "supply-chain"),
               integration("kingdee", "supply-chain")),
        target="organization",
    )
    assert len(rows) == 1


def test_connectivity_is_copied_verbatim():
    rows = importer.plans(
        status(integration("shopify_admin", "crossborder", catalog=True,
                           executor_tests=True, live=False)),
        target="organization",
    )
    conn = rows[0]["connectivity"]
    assert conn["catalog"]["ok"] is True
    assert conn["live"]["ok"] is False
    assert rows[0]["missing"] == ["live"]


def test_no_confidence_is_invented():
    """The ERP file says nothing about how sure anyone is — so we say nothing."""
    rows = importer.plans(
        status(integration("kingdee", "supply-chain", catalog=True)), target="organization"
    )
    assert "confidence" not in rows[0], (
        "a synthesised confidence would count as reviewed something nobody reviewed"
    )


def test_missing_states_are_listed_in_clearance_order():
    rows = importer.plans(
        status(integration("pos", "restaurant-chain", catalog=True)), target="organization"
    )
    assert rows[0]["missing"] == ["executor_tests", "live"]


def test_fully_connected_reports_no_missing():
    rows = importer.plans(
        status(integration("wms", "supply-chain", catalog=True,
                           executor_tests=True, live=True)),
        target="organization",
    )
    assert rows[0]["missing"] == []


def test_rows_without_provider_or_template_are_skipped():
    rows = importer.plans(
        status({"provider": "", "template": "x"}, {"provider": "y", "template": ""}),
        target="organization",
    )
    assert rows == []


# ---------------------------------------------------------------- real file


def test_plans_validate_against_the_real_crosswalk_rules():
    """Whatever we import must pass the same predicate the proposal inbox uses."""
    from src.bench import crosswalk as cw

    real = REPO_ROOT.parent / "fd-erp-vertical-templates" / "connector-status.json"
    if not real.is_file():
        pytest.skip("ERP checkout not present")
    rows = importer.plans(json.loads(real.read_text(encoding="utf-8")),
                          target="organization")
    assert rows, "the real file has integrations"
    for row in rows:
        attrs = {
            "relation": "same_as",
            "peer": {"kind": "external_id", "system": row["provider"],
                     "id": row["provider"]},
            "connectivity": row["connectivity"],
        }
        assert cw.validate_crosswalk(attrs) == [], row["provider"]


def test_write_path_creates_only_the_crosswalk_no_provider_entity(monkeypatch):
    """The import must not manufacture a unit for the peer.

    Pinned because the removed step was invisible from the output: the summary
    line said "entities: +N", and a template without an `external_system` type
    failed the whole import with `ValueError: domain ... not found` — a message
    that points at the domain, not at the offending step.
    """
    import types

    created: list[tuple[str, str]] = []

    class FakeAuthoring:
        @staticmethod
        def authoring_create_unit(conn, **kw):
            created.append(("unit", kw["kind"]))
            return {}

        @staticmethod
        def authoring_create_crosswalk(conn, **kw):
            created.append(("crosswalk", kw["external_key"]))
            return {}

    class FakeStore:
        @staticmethod
        def get_knowledge_unit(conn, **kw):
            return None          # nothing exists yet → created, not updated

    fake_conn = types.SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(
        connect=lambda *a, **k: fake_conn,
        rows=types.SimpleNamespace(dict_row=None),
    ))
    monkeypatch.setattr(importer, "load_status", lambda p: status(
        integration("wechatpay", "supply-chain", catalog=True, executor_tests=True),
    ))

    # The function imports these inside main(); patch them on the source modules.
    import src.bench.authoring as real_authoring
    import src.bench.store as real_store
    import src.eval.store as real_eval_store
    import src.eval.db as real_edb
    monkeypatch.setattr(real_authoring, "authoring_create_unit",
                        FakeAuthoring.authoring_create_unit)
    monkeypatch.setattr(real_authoring, "authoring_create_crosswalk",
                        FakeAuthoring.authoring_create_crosswalk)
    monkeypatch.setattr(real_store, "get_knowledge_unit", FakeStore.get_knowledge_unit)
    monkeypatch.setattr(real_eval_store, "ensure_schema", lambda **kw: None)
    monkeypatch.setattr(real_edb, "_dsn", lambda: "postgresql://fake/db")
    # `main` reads back the landed count, so the fake must answer that too.
    committed = {"n": 0}
    monkeypatch.setattr(fake_conn, "commit", lambda: committed.update(n=1), raising=False)
    import src.bench.crosswalk as real_cw
    monkeypatch.setattr(real_cw, "list_rows", lambda conn, namespace: [1])

    importer.main(["--domain", "erp", "--force"])

    kinds = [k for k, _ in created]
    assert kinds == ["crosswalk"], f"only the crosswalk may be written, got {created}"
    assert created[0][1] == "organization:wechatpay"
    # Without an explicit commit psycopg3 rolls back on close: the run would
    # report "+1 new" and write nothing (that is exactly what happened on
    # production 2026-11-19).
    assert committed["n"] == 1, "the import must commit before closing"
