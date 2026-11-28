"""Portable asset transfer (change add-bench-asset-portability).

Pins the properties that make a copy auditable rather than merely a copy:

- one content digest: an envelope's digest equals the kernel's canonical
  sha256 of its payload;
- whole-or-nothing: a tampered envelope lands nothing;
- a fork records its source and its difference, and a fork that removes an
  upstream vocabulary entry is refused;
- only a successful import leaves an audit row.
"""

from __future__ import annotations

import pytest

from fd_ontology_kernel import envelope as kernel_envelope
from fd_ontology_kernel import manifest as kernel_manifest

from src.bench import asset_transfer, domain_rubrics, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval import store as eval_store
from src.eval.store import ensure_schema


def _schema(entity_types=("company", "person")) -> dict:
    return {
        "layer": "domain",
        "authority": {"kind": "platform"},
        "entity_types": list(entity_types),
        "concept_structures": {},
        "relationship_kinds": ["employs"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            context TEXT,
            source TEXT,
            source_path TEXT,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    empty_db.commit()
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    yield empty_db


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("BENCH_ASSET_PORTABILITY", "1")


def test_export_digest_is_the_kernel_digest(conn):
    templates.create_template(conn, name="official-x", schema=_schema(), created_by="t")
    env = asset_transfer.export_asset(conn, kind="ontology-template", name="official-x")
    assert env["digest"] == kernel_manifest.digest_of(_schema())
    assert env["manifest_shape"] == 2


def test_fork_import_records_lineage_and_digest(conn):
    templates.create_template(conn, name="official-x", schema=_schema(), created_by="t")
    source = asset_transfer.export_asset(
        conn, kind="ontology-template", name="official-x"
    )

    fork = kernel_envelope.build(
        kind="ontology-template",
        name="mine-x",
        version=1,
        payload=_schema(entity_types=("company", "person", "project")),
        manifest_shape=2,
        lineage={
            "upstream": {
                "name": source["name"],
                "version": source["version"],
                "digest": source["digest"],
            }
        },
        fork_diff={"added": ["project"]},
    )
    result = asset_transfer.import_asset(conn, raw=fork, actor="admin")
    assert result["created"] is True
    parent = templates.get_template(conn, name="official-x")
    assert result["derived_from"] == parent["id"]
    imported = templates.get_template(conn, name="mine-x")
    assert imported["fork_diff"] == {"added": ["project"]}
    assert imported["upstream"]["digest"] == source["digest"]
    audit = conn.execute(
        "SELECT asset_kind, digest FROM asset_transfer_events"
    ).fetchall()
    assert audit and audit[0]["digest"] == fork["digest"]


def test_import_is_idempotent_on_same_content(conn):
    templates.create_template(conn, name="official-x", schema=_schema(), created_by="t")
    source = asset_transfer.export_asset(
        conn, kind="ontology-template", name="official-x"
    )
    fork = kernel_envelope.build(
        kind="ontology-template",
        name="mine-x",
        version=1,
        payload=_schema(),
        manifest_shape=2,
        lineage={
            "upstream": {
                "name": source["name"],
                "version": source["version"],
                "digest": source["digest"],
            }
        },
        fork_diff={"note": "same vocab"},
    )
    assert asset_transfer.import_asset(conn, raw=fork, actor="a")["created"] is True
    again = asset_transfer.import_asset(conn, raw=fork, actor="a")
    assert again["created"] is False
    assert templates.get_template(conn, name="mine-x")["version"] == 1


def test_tampered_envelope_lands_nothing(conn):
    raw = kernel_envelope.build(
        kind="ontology-template",
        name="evil",
        version=1,
        payload=_schema(),
        manifest_shape=2,
    )
    raw["payload"]["entity_types"].append("injected")
    with pytest.raises(asset_transfer.TransferError):
        asset_transfer.import_asset(conn, raw=raw, actor="a")
    assert templates.get_template(conn, name="evil") is None
    assert conn.execute("SELECT count(*) AS n FROM asset_transfer_events").fetchone()["n"] == 0


def test_fork_removing_upstream_type_is_refused(conn):
    templates.create_template(conn, name="official-x", schema=_schema(), created_by="t")
    source = asset_transfer.export_asset(
        conn, kind="ontology-template", name="official-x"
    )
    fork = kernel_envelope.build(
        kind="ontology-template",
        name="bad-fork",
        version=1,
        payload=_schema(entity_types=("company",)),
        manifest_shape=2,
        lineage={
            "upstream": {
                "name": source["name"],
                "version": source["version"],
                "digest": source["digest"],
            }
        },
        fork_diff={"removed": ["person"]},
    )
    with pytest.raises(asset_transfer.TransferError) as exc:
        asset_transfer.import_asset(conn, raw=fork, actor="a")
    assert "person" in str(exc.value)
    assert templates.get_template(conn, name="bad-fork") is None


def test_ruler_set_roundtrips_between_domains(conn):
    tmpl = templates.create_template(conn, name="official-x", schema=_schema(), created_by="t")
    a = workspaces.instantiate_domain(
        conn, key="domain-a", name="A", template_name="official-x",
        template_version=tmpl["version"], created_by="t",
    )
    b = workspaces.instantiate_domain(
        conn, key="domain-b", name="B", template_name="official-x",
        template_version=tmpl["version"], created_by="t",
    )
    domain_rubrics.create_for_domain(
        conn, domain_id=a["id"], name="contract-quality",
        context="contracts", criteria=[{"name": "clarity", "description": "clear"}],
        source="local",
    )
    env = asset_transfer.export_asset(
        conn, kind="ruler-set", name="domain-a", domain_key="domain-a"
    )
    result = asset_transfer.import_asset(
        conn, raw=env, actor="a", target_domain_key="domain-b"
    )
    assert result["imported"] == ["contract-quality"]
    again = asset_transfer.import_asset(
        conn, raw=env, actor="a", target_domain_key="domain-b"
    )
    assert again["created"] is False
    assert again["skipped"] == ["contract-quality"]
    names = [
        r["name"]
        for r in domain_rubrics.effective_rubrics(
            conn, domain_path=workspaces.get_domain(conn, domain_key="domain-b")["path"]
        )
    ]
    assert "contract-quality" in names


def test_export_only_kind_refuses_import_loudly(conn):
    env = kernel_envelope.build(
        kind="gold-set", name="g", version=1,
        payload={"domain": "x", "units": []}, manifest_shape=2,
    )
    with pytest.raises(asset_transfer.TransferError) as exc:
        asset_transfer.import_asset(conn, raw=env, actor="a")
    assert "export-only" in str(exc.value)


def test_disabled_surface_refuses(conn, monkeypatch):
    monkeypatch.delenv("BENCH_ASSET_PORTABILITY", raising=False)
    with pytest.raises(asset_transfer.TransferError) as exc:
        asset_transfer.export_asset(conn, kind="ontology-template", name="x")
    assert "not enabled" in str(exc.value)
