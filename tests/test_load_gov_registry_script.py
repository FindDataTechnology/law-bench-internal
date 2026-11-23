"""scripts/load_gov_registry.py — land the registry + score the gov domain.

Runs against the REAL sibling registry (``<workspace>/fd-cn-gov``) so the
assertions are on real data (skipped when the checkout is absent). Covers:

- ``--dry-run`` writes nothing (dry run must not touch the DB);
- a real load lands the 11 ``gov-fact`` units in ``namespace='gov'`` and is
  idempotent (two runs, same count, no duplicate rows);
- the script's post-load data evaluation writes a run attributed to the gov
  domain (``rubric_domain_id`` non-null), the same C1 attribution the console
  button relies on.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from src.bench import templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_REPO = REPO_ROOT.parent / "fd-cn-gov"
REAL_REGISTRY = REAL_REPO / "fd_cn_gov" / "registry" / "registry.json"

pytestmark = pytest.mark.skipif(
    not REAL_REGISTRY.exists(), reason="real fd-cn-gov registry not present"
)


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    # The script's post-load eval resolves the gov domain; prod has one, so the
    # fixture must too or run_domain_data_eval would raise on a missing domain.
    schema = {
        "entity_types": ["gov-fact", "document"],
        "concept_structures": {},
        "relationship_kinds": ["issued_by"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl-gov", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="gov", name="政务", template_name="tpl-gov",
        template_version=None, created_by="t",
    )
    empty_db.commit()
    yield empty_db


SCRIPT = REPO_ROOT / "scripts" / "load_gov_registry.py"


def _script():
    # scripts/ is not a package; load the module by path (repo convention).
    spec = importlib.util.spec_from_file_location("load_gov_registry_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_writes_nothing(db_conn, monkeypatch):
    monkeypatch.setenv("FD_GOV_REPO", str(REAL_REPO))
    rc = _script().main(["--dry-run"])
    assert rc == 0
    rows = db_conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE kind = 'gov-fact'"
    ).fetchone()
    assert rows["n"] == 0


def test_load_is_idempotent_and_lands_then_evals(db_conn, monkeypatch):
    monkeypatch.setenv("FD_GOV_REPO", str(REAL_REPO))
    mod = _script()
    # First run: land + eval.
    assert mod.main([]) == 0
    first = db_conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE kind = 'gov-fact' "
        "AND namespace = 'gov'"
    ).fetchone()["n"]
    assert first == 11
    # Idempotent: second load keeps the same count (no duplicate rows).
    from packs.gov import adapters
    adapters.load_gov_registry(db_conn)
    second = db_conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE kind = 'gov-fact' "
        "AND namespace = 'gov'"
    ).fetchone()["n"]
    assert second == first


def test_the_eval_run_is_attributed_to_the_gov_domain(db_conn, monkeypatch):
    monkeypatch.setenv("FD_GOV_REPO", str(REAL_REPO))
    _script().main(["--no-eval"])  # land units only, no eval
    # run the eval explicitly so we can assert attribution
    from src.bench import data_eval
    import packs.gov.checks  # noqa: F401 - register gov-fact checkers
    out = data_eval.run_domain_data_eval(db_conn, domain_key="gov")
    assert out["outcome"] == "pass"
    assert out["n_criteria"] > 0
    # attribution: the run points at the gov domain (requires the domain to exist)
    row = db_conn.execute(
        "SELECT rubric_domain_id FROM eval_runs WHERE id = %s", (out["run_ids"][0],)
    ).fetchone()
    gov = db_conn.execute("SELECT id FROM domains WHERE key = 'gov'").fetchone()
    assert row["rubric_domain_id"] == gov["id"], "gov data eval must be domain-attributed"
    runs = db_conn.execute(
        "SELECT channel, outcome FROM eval_runs WHERE id = %s", (out["run_ids"][0],)
    ).fetchone()
    assert runs["channel"] == "data"
