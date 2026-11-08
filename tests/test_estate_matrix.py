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

    # Now ingest one chunk so the corpus pillar is genuinely satisfied — the
    # gap is about retrievable content, not about a subscription row.
    lib = libraries.get_library(conn, library_key="law")
    conn.execute(
        "INSERT INTO corpus_chunks (library_id, scope_path, source_key, doc_path, "
        "chunk_seq, content, content_hash) VALUES (%s, %s, 'statutes', 'd.md', 0, 'b', 'h')",
        (lib["id"], root["path"]),
    )
    conn.commit()

    rows = estate.matrix(conn, domains=domains)
    assert rows[0]["gaps"] == []
    assert rows[0]["knowledge"]["chunks"] == 1
    assert rows[0]["knowledge"]["libraries"] == 1
    assert rows[0]["knowledge"]["sources"] == 1

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


def test_unreachable_store_is_unknown_not_a_gap(conn, monkeypatch):
    """An unreadable corpus must not be reported as a missing one.

    If Qdrant is down, the count fails. Marking the domain as "缺语料" would send
    an operator to rebuild a corpus that already exists — the opposite of the
    failure this page exists to prevent. The row still carries the error.
    """
    domains = _domains(conn)
    root = domains[0]
    libraries.create_library(conn, library_key="law", name="Law", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    libraries.add_source(conn, library_key="law", source_key="statutes", uri="x", created_by="t")
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    conn.commit()
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test:6333")

    import httpx
    from src.search import library_index

    def boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(library_index, "_http_post", boom)
    rows = estate.matrix(conn, domains=domains)
    row = rows[0]
    assert "error" in row["knowledge"]
    assert "knowledge" not in row["gaps"]      # unknown, not empty
    assert "connection refused" in row["knowledge"]["error"]


def test_inherited_grant_is_counted_once_for_many_domains(conn, monkeypatch):
    """Ten sub-domains inheriting one grant must not mean ten store round trips.

    The memo is per-request, so this is a latency fix, never a stale number: a
    fresh call always re-counts.
    """
    templates.create_template(conn, name="tpl2", schema=_schema(), created_by="t")
    tid = conn.execute("SELECT id FROM ontology_templates ORDER BY id DESC LIMIT 1").fetchone()["id"]
    root = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('top','Top',%s,1,'t','top') RETURNING id, key, name, path, template_id",
        (tid,),
    ).fetchone()
    kids = []
    for i in range(5):
        kids.append(dict(conn.execute(
            "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
            "VALUES (%s,%s,%s,1,'t',%s,%s) RETURNING id, key, name, path, template_id",
            (f"k{i}", f"K{i}", tid, root["id"], f"top/k{i}"),
        ).fetchone()))
    conn.commit()
    libraries.create_library(conn, library_key="law", name="Law", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    libraries.add_source(conn, library_key="law", source_key="s1", uri="x", created_by="t")
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    conn.commit()

    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test:6333")
    import httpx
    from src.search import library_index as li

    calls = {"n": 0}

    def stub(url, *, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(200, json={"result": {"count": 42}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(li, "_http_post", stub)
    rows = estate.matrix(conn, domains=[dict(root)] + kids)
    assert [r["knowledge"]["chunks"] for r in rows] == [42] * 6
    assert calls["n"] == 1
