"""Estate gap matrix (§4.2).

The matrix is the only page that answers "what is missing where" across many
sub-domains, so its two load-bearing behaviours are pinned here:

- a domain with an empty pillar is reported as a gap, and a domain with data is
  not (no false alarm — the whole point is trusting this page);
- filtering keeps exactly the domains missing the selected pillar;
- an unreadable scope (a stored subscription that would widen its parent) is
  reported as an error instead of silently reading as "no corpus", because
  "0 sources" and "broken subscription" need different fixes.
"""

from __future__ import annotations

import pytest

from src.bench import estate, libraries, templates
from src.bench.tiers import TIERS
from src.bench.promotion import SENSITIVITY_LEVELS
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # rubrics/criteria come from a legacy seed script, not ensure_schema; the
    # evaluation pillar reads them, so recreate the deployed shape here.
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
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    yield empty_db


def _schema() -> dict:
    return {
        "entity_types": ["clause", "law"],
        "concept_structures": {"clause": ["id"]},
        "relationship_kinds": ["cites_law"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["uploaded"]},
    }


def _domains(conn):
    templates.create_template(conn, name="tpl", schema=_schema(), created_by="t")
    tid = conn.execute("SELECT id FROM ontology_templates LIMIT 1").fetchone()["id"]
    root = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('legal','Legal',%s,1,'t','legal') RETURNING id, key, name, path, template_id",
        (tid,),
    ).fetchone()
    child = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('cr','CR',%s,1,'t',%s,'legal/cr') "
        "RETURNING id, key, name, path, template_id",
        (tid, root["id"]),
    ).fetchone()
    conn.commit()
    return [dict(root), dict(child)]


def test_empty_domain_reports_every_gap(conn):
    domains = _domains(conn)
    rows = estate.matrix(conn, domains=domains)
    assert [r["gaps"] for r in rows] == [["ontology", "knowledge", "eval"]] * 2
    # The declared vocabulary is still readable even when nothing is curated.
    assert rows[0]["ontology"]["declared_types"] == 2
    assert rows[0]["ontology"]["curated_units"] == 0


def test_populated_pillars_are_not_gaps(conn):
    domains = _domains(conn)
    root = domains[0]
    # ontology
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('entity','legal','party','b','now','now')"
    )
    # corpus
    libraries.create_library(conn, library_key="law", name="Law", created_by="t")
    libraries.add_source(conn, library_key="law", source_key="statutes", uri="s3://b/s", created_by="t")
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    # evaluation standard
    conn.execute(
        "INSERT INTO rubrics (name, context, source, description, domain_id) "
        "VALUES ('quality','check','seed','d',%s)",
        (root["id"],),
    )
    conn.commit()

    rows = estate.matrix(conn, domains=domains)
    assert rows[0]["gaps"] == []
    assert rows[0]["knowledge"] == {"libraries": 1, "sources": 1}
    assert rows[0]["eval"]["standards"] == 1
    # The child inherits the standard and the corpus, but has no units of its own.
    assert rows[1]["gaps"] == ["ontology"]
    assert rows[1]["knowledge"]["sources"] == 1


def test_filter_keeps_only_affected_domains(conn):
    domains = _domains(conn)
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('entity','legal','party','b','now','now')"
    )
    conn.commit()
    rows = estate.matrix(conn, domains=domains)
    only_knowledge = estate.filter_rows(rows, "knowledge")
    assert [r["domain"]["key"] for r in only_knowledge] == ["legal", "cr"]
    # Only the child still lacks curated units: the root just got one.
    assert [r["domain"]["key"] for r in estate.filter_rows(rows, "ontology")] == ["cr"]
    assert estate.filter_rows(rows, None) == rows


def test_scope_violation_is_reported_not_silently_zero(conn):
    domains = _domains(conn)
    root, child = domains
    libraries.create_library(conn, library_key="law", name="Law", created_by="t")
    for key in ("statutes", "contracts"):
        libraries.add_source(conn, library_key="law", source_key=key, uri=f"s3://b/{key}", created_by="t")
    libraries.subscribe(
        conn, domain_id=root["id"], library_key="law", created_by="t", source_filter=["statutes"]
    )
    libraries.subscribe(
        conn, domain_id=child["id"], library_key="law", created_by="t",
        source_filter=["statutes", "contracts"],
    )
    conn.commit()
    rows = estate.matrix(conn, domains=domains)
    child_row = [r for r in rows if r["domain"]["key"] == "cr"][0]
    assert "error" in child_row["knowledge"]
    assert "widen" in child_row["knowledge"]["error"] or "widens" in child_row["knowledge"]["error"]
