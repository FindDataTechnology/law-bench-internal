"""Domain-scoped data evaluation + domain attribution (change deepen-industry-lines C1).

Covers the three things C1 exists to fix, each on its own throwaway DB:

- ``store_result`` fills ``rubric_domain_id`` when the rubric name resolves to a
  single owning domain, and leaves it NULL when it does not (zero/multiple) — no
  fabricated provenance.
- ``run_domain_data_eval`` runs the domain's evaluable kinds over its **live**
  units and attributes the conclusion to the domain, so ``estate`` / run lists
  (which join on ``rubric_domain_id``) can see it.
- a domain with no live units of an evaluable kind records ``inconclusive``,
  never a pass.
"""

from __future__ import annotations

import pytest

from src.bench import data_checks, data_eval, store, workspaces, templates, authoring
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema, store_result

KIND = "probe-entity"


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    yield empty_db


@pytest.fixture()
def registry():
    saved = {k: dict(v) for k, v in data_checks._CHECKERS.items()}
    yield data_checks
    data_checks._CHECKERS.clear()
    data_checks._CHECKERS.update(saved)


def _schema():
    return {
        "entity_types": ["probe-entity"],
        "concept_structures": {},
        "relationship_kinds": ["relates_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def _make_domain(conn, key):
    tmpl = templates.create_template(conn, name=f"tpl-{key}", schema=_schema(), created_by="admin-1")
    return workspaces.instantiate_domain(
        conn, key=key, name=f"Domain {key}", template_name=f"tpl-{key}",
        template_version=tmpl["version"], created_by="admin-1",
    )


def _rubric(conn, *, name, domain_id):
    return conn.execute(
        "INSERT INTO rubrics (name, context, source, created_at, domain_id) "
        "VALUES (%s, 'check', 'platform-seed', 'now', %s) RETURNING id",
        (name, domain_id),
    ).fetchone()["id"]


# ------------------------------------------------------------ attribution


def test_store_result_fills_domain_when_rubric_uniquely_owned(db_conn):
    dom = _make_domain(db_conn, "dom-attr")
    _rubric(db_conn, name="data-checks:probe-entity", domain_id=dom["id"])
    db_conn.commit()

    run_id = store_result(
        {"rubric": "data-checks:probe-entity", "score": 1, "max_score": 1,
         "all_pass": True, "n_criteria": 1, "n_passed": 1, "criteria_results": []},
        db_path=db_conn, channel="data", unit_kind="probe-entity",
    )
    row = db_conn.execute(
        "SELECT rubric_domain_id FROM eval_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row["rubric_domain_id"] == dom["id"]


def test_store_result_leaves_null_when_rubric_absent(db_conn):
    run_id = store_result(
        {"rubric": "no-such-rubric", "score": 1, "max_score": 1,
         "all_pass": True, "n_criteria": 1, "n_passed": 1, "criteria_results": []},
        db_path=db_conn, channel="data", unit_kind="x",
    )
    row = db_conn.execute(
        "SELECT rubric_domain_id FROM eval_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row["rubric_domain_id"] is None


def test_store_result_leaves_null_when_rubric_owned_by_two_domains(db_conn):
    a = _make_domain(db_conn, "dom-a")
    b = _make_domain(db_conn, "dom-b")
    _rubric(db_conn, name="dup-rubric", domain_id=a["id"])
    _rubric(db_conn, name="dup-rubric", domain_id=b["id"])
    db_conn.commit()

    run_id = store_result(
        {"rubric": "dup-rubric", "score": 1, "max_score": 1, "all_pass": True,
         "n_criteria": 1, "n_passed": 1, "criteria_results": []},
        db_path=db_conn, channel="data", unit_kind="x",
    )
    row = db_conn.execute(
        "SELECT rubric_domain_id FROM eval_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row["rubric_domain_id"] is None


# ------------------------------------------------------ domain data eval


def test_run_domain_data_eval_attributes_and_counts(db_conn, registry, monkeypatch):
    dom = _make_domain(db_conn, "dom-de")
    # one kind declared by the (faked) pack, with a checker
    monkeypatch.setattr(data_eval.packs, "load_pack", lambda key: {"kinds": [KIND]})
    registry.register_checker(KIND, "nonempty", lambda u: bool(u.get("body")))
    for i in range(2):
        authoring.authoring_create_unit(
            db_conn, domain_key="dom-de", kind=KIND,
            external_key=f"e-{i}", body="has body", operator="expert-1",
        )
    # a deleted unit must be excluded
    authoring.authoring_create_unit(
        db_conn, domain_key="dom-de", kind=KIND,
        external_key="e-gone", body="x", operator="expert-1",
    )
    authoring.authoring_delete_unit(
        db_conn, domain_key="dom-de", kind=KIND,
        external_key="e-gone", operator="expert-1",
    )

    out = data_eval.run_domain_data_eval(db_conn, domain_key="dom-de", db_path=db_conn)
    assert out["outcome"] == "pass"
    assert out["n_units"] == 2
    assert len(out["run_ids"]) == 1
    row = db_conn.execute(
        "SELECT rubric_domain_id FROM eval_runs WHERE id = %s", (out["run_ids"][0],)
    ).fetchone()
    assert row["rubric_domain_id"] == dom["id"]


def test_run_domain_data_eval_inconclusive_without_units(db_conn, registry, monkeypatch):
    _make_domain(db_conn, "dom-empty-eval")
    monkeypatch.setattr(data_eval.packs, "load_pack", lambda key: {"kinds": [KIND]})
    registry.register_checker(KIND, "nonempty", lambda u: True)

    out = data_eval.run_domain_data_eval(db_conn, domain_key="dom-empty-eval", db_path=db_conn)
    assert out["outcome"] == "inconclusive"
    assert out["run_ids"] == []


def test_run_domain_data_eval_raises_on_unknown_domain(db_conn):
    with pytest.raises(ValueError):
        data_eval.run_domain_data_eval(db_conn, domain_key="nope", db_path=db_conn)
