"""Typed publication kinds + kernel publish (change add-typed-publications).

Covers tasks 1.1-1.4 and 2.1-2.7 at the kernel level (no HTTP):

- registry: a pack registers kinds; an unregistered kind is refused naming the
  registered ones (never an empty catalogue); no pack loaded -> empty registry
  and the process still works; the kernel module carries no industry strings.
- projection: entries come from the domain's *shelf* only, are normalized and
  sorted, an empty shelf is refused, duplicate keys are refused.
- digest: the SAME ``canonical_digest`` as the ontology snapshot (byte-equal);
  ``shape_version`` lives outside the payload and never enters the digest.
- publish: monotonic versions, idempotent on identical content, changelog with
  added/removed/changed, and no effect at all on ``domain_assets`` ownership.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.bench import distribution, domain_assets, publication_kinds, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.harbor_seed import create_schema as create_harbor_schema
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]

RUBRIC_PROVIDER = {
    "relation": (
        "SELECT r.name AS asset_key, r.name AS name, r.context AS summary "
        "FROM rubrics r"
    ),
    "label_key": "bench_catalog.kind.rubric",
    "sort_key": "name",
    "shape_version": 1,
}


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    create_harbor_schema(empty_db)
    yield empty_db


@pytest.fixture()
def kinds(monkeypatch):
    """Register only the test provider for the duration of one test."""
    monkeypatch.setattr(publication_kinds, "_PROVIDERS", {})
    monkeypatch.setattr(publication_kinds, "KINDS", ())
    publication_kinds.register_kinds({"rubric": RUBRIC_PROVIDER})
    return {"rubric": RUBRIC_PROVIDER}


def make_domain(conn, key: str) -> dict:
    tmpl = templates.create_template(
        conn,
        name=f"tpl-{key}",
        schema={
            "entity_types": ["company"],
            "concept_structures": {},
            "relationship_kinds": ["belongs_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {},
        },
        created_by="admin-1",
    )
    return workspaces.instantiate_domain(
        conn, key=key, name=f"Domain {key}", template_name=f"tpl-{key}",
        template_version=tmpl["version"], created_by="admin-1",
    )


def make_rubric(conn, name: str, context: str = "check") -> None:
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, "
        "created_at) VALUES (%s, %s, 'local', NULL, '', '2026-01-01T00:00:00+00:00')",
        (name, context),
    )
    conn.commit()


def shelve(conn, domain_key: str, key: str) -> None:
    domain_assets.assign(
        conn, domain_key=domain_key, asset_kind="rubric", asset_key=key,
        added_by="admin-1", providers={"rubric": {
            "relation": RUBRIC_PROVIDER["relation"],
            "label_key": RUBRIC_PROVIDER["label_key"],
        }},
    )


# ------------------------------------------------------------- 1. registry


def test_unregistered_kind_is_refused_naming_the_registered_ones(kinds):
    with pytest.raises(ValueError) as exc:
        publication_kinds.resolve("sample")
    assert "rubric" in str(exc.value)
    assert "'sample'" in str(exc.value)


def test_empty_registry_refuses_instead_of_serving_nothing(monkeypatch):
    monkeypatch.setattr(publication_kinds, "_PROVIDERS", {})
    monkeypatch.setattr(publication_kinds, "KINDS", ())
    with pytest.raises(ValueError):
        publication_kinds.resolve("rubric")


def test_kernel_has_no_industry_strings_and_starts_without_a_pack():
    """1.4: the kernel module is domain-free and an unloaded pack is not fatal."""
    source = (REPO_ROOT / "src" / "bench" / "publication_kinds.py").read_text(encoding="utf-8")
    for term in ("law_catalog", "contract_type", "民法典", "合同", "rubric", "sample"):
        assert term not in source, f"industry term {term!r} leaked into the kernel"

    out = subprocess.run(
        [sys.executable, "-c",
         "from src.bench import publication_kinds as p; print(list(p.list_kinds()))"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ----------------------------------------------------------- 1./2. projection


def test_projection_reads_only_the_shelf_and_is_order_independent(db_conn, kinds):
    make_domain(db_conn, "d1")
    make_rubric(db_conn, "r-b")
    make_rubric(db_conn, "r-a")
    shelve(db_conn, "d1", "r-b")
    shelve(db_conn, "d1", "r-a")
    make_rubric(db_conn, "r-not-shelved")

    domain = workspaces.get_domain(db_conn, domain_key="d1")
    manifest = publication_kinds.build_manifest(
        db_conn, domain_id=domain["id"], asset_kind="rubric"
    )
    assert [e["asset_key"] for e in manifest["entries"]] == ["r-a", "r-b"]


def test_empty_shelf_is_refused(db_conn, kinds):
    make_domain(db_conn, "d1")
    domain = workspaces.get_domain(db_conn, domain_key="d1")
    with pytest.raises(ValueError, match="nothing to publish"):
        publication_kinds.build_manifest(
            db_conn, domain_id=domain["id"], asset_kind="rubric"
        )


# -------------------------------------------------------------- 2.2 2.3 digest


def test_publish_digest_is_the_shared_canonical_digest(db_conn, kinds):
    make_domain(db_conn, "d1")
    make_rubric(db_conn, "r-a")
    shelve(db_conn, "d1", "r-a")
    domain = workspaces.get_domain(db_conn, domain_key="d1")

    publication = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    rebuilt = publication_kinds.build_manifest(
        db_conn, domain_id=domain["id"], asset_kind="rubric"
    )
    assert publication["digest"] == distribution.canonical_digest(rebuilt)


def test_shape_version_is_outside_the_payload_and_the_digest(db_conn, kinds):
    make_domain(db_conn, "d1")
    make_rubric(db_conn, "r-a")
    shelve(db_conn, "d1", "r-a")

    v1 = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    assert "shape_version" not in (v1["manifest"] or {})
    assert v1["shape_version"] == 1

    bumped = {**RUBRIC_PROVIDER, "shape_version": 2}
    publication_kinds.register_kinds({"rubric": bumped})
    v2 = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    # Same content: the digest is unchanged, so the idempotent path returns v1.
    assert v2["digest"] == v1["digest"]
    assert v2["version"] == v1["version"]
    assert "shape_version" not in (v2["manifest"] or {})


# ------------------------------------------------------- 2.4 2.5 2.6 publish


def test_empty_kind_cannot_be_published(db_conn, kinds):
    make_domain(db_conn, "d1")
    with pytest.raises(ValueError, match="nothing to publish"):
        distribution.publish_asset_kind(
            db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
        )
    rows = db_conn.execute("SELECT count(*) AS n FROM asset_publications").fetchone()
    assert rows["n"] == 0


def test_republish_is_idempotent_and_changes_produce_a_changelog(db_conn, kinds):
    make_domain(db_conn, "d1")
    make_rubric(db_conn, "r-a", context="first")
    make_rubric(db_conn, "r-b")
    shelve(db_conn, "d1", "r-a")

    v1 = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    assert v1["version"] == 1
    assert v1["changelog"] == {"initial": True, "counts": {"entries": 1}}

    again = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    assert (again["version"], again["digest"]) == (v1["version"], v1["digest"])
    assert db_conn.execute(
        "SELECT count(*) AS n FROM asset_publications"
    ).fetchone()["n"] == 1

    db_conn.execute("UPDATE rubrics SET context = 'second' WHERE name = 'r-a'")
    db_conn.commit()
    shelve(db_conn, "d1", "r-b")
    v2 = distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    assert v2["version"] == 2
    assert v2["changelog"]["added"] == ["r-b"]
    assert v2["changelog"]["removed"] == []
    assert v2["changelog"]["changed"][0]["key"] == "r-a"
    assert v2["changelog"]["changed"][0]["fields"]["summary"] == {
        "before": "first", "after": "second",
    }
    assert v2["changelog"]["counts"] == {"entries": 2}

    # The published v1 snapshot is untouched by later edits.
    v1_again = distribution.get_asset_publication(
        db_conn, domain_key="d1", asset_kind="rubric", version=1
    )
    assert v1_again["digest"] == v1["digest"]
    assert v1_again["manifest"]["entries"][0]["summary"] == "first"


def test_publishing_never_changes_ownership(db_conn, kinds):
    make_domain(db_conn, "d1")
    make_rubric(db_conn, "r-a")
    make_rubric(db_conn, "r-b")
    shelve(db_conn, "d1", "r-a")
    shelve(db_conn, "d1", "r-b")
    before = db_conn.execute(
        "SELECT domain_id, asset_kind, asset_key FROM domain_assets ORDER BY 3"
    ).fetchall()

    distribution.publish_asset_kind(
        db_conn, domain_key="d1", asset_kind="rubric", published_by="admin-1"
    )
    after = db_conn.execute(
        "SELECT domain_id, asset_kind, asset_key FROM domain_assets ORDER BY 3"
    ).fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before]

    # Unassigning does not delete the published version (spec scenario).
    domain_assets.unassign(
        db_conn, domain_key="d1", asset_kind="rubric", asset_key="r-a",
        providers={"rubric": {"relation": RUBRIC_PROVIDER["relation"],
                              "label_key": RUBRIC_PROVIDER["label_key"]}},
    )
    still = distribution.get_asset_publication(
        db_conn, domain_key="d1", asset_kind="rubric"
    )
    assert still is not None and still["version"] == 1