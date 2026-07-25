"""Unit tests for src/eval/manage.py against a throwaway SQLite DB.

Loads the real schema from scripts/extract_harbor_rules.py (single source of
truth), seeds one harbor and one local rubric, then exercises the CRUD + guard
behavior.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from src.eval import manage as M
from src.eval.manage import (
    ConflictError,
    HarborReadOnlyError,
    NotFoundError,
    ValidationError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_extract_module():
    spec = importlib.util.spec_from_file_location(
        "extract_harbor_rules", REPO_ROOT / "scripts" / "extract_harbor_rules.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A temp DB with the real schema + one harbor and one local rubric."""
    extract = _load_extract_module()
    db_path = tmp_path / "test_rules.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    extract.create_schema(conn)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES ('h_rubric', 'check', 'harbor:v0.20.0', 'p.toml', 'harbor test', ?)",
        (now,),
    )
    h_id = conn.execute(
        "SELECT id FROM rubrics WHERE name = 'h_rubric'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "VALUES (?, 'h_c1', 'hd', 'hg', 0)",
        (h_id,),
    )

    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES ('l_rubric', 'contract', 'local', NULL, 'local test', ?)",
        (now,),
    )
    l_id = conn.execute(
        "SELECT id FROM rubrics WHERE name = 'l_rubric'"
    ).fetchone()[0]
    for i, name in enumerate(["c1", "c2"]):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (?, ?, 'd', 'g', ?)",
            (l_id, name, i),
        )
    conn.commit()
    conn.close()
    return db_path


def _local_id(db: Path) -> int:
    return M.get_rubric_detail("l_rubric", db_path=db)["id"]


def _harbor_id(db: Path) -> int:
    return M.get_rubric_detail("h_rubric", db_path=db)["id"]


# --- create ---------------------------------------------------------------- #


def test_create_local_rubric_with_criteria(db: Path):
    created = M.create_rubric(
        "new_rubric",
        "contract",
        "a new rubric",
        [
            {"name": "a", "description": "da", "guidance": "ga"},
            {"name": "b", "description": "db", "guidance": "gb"},
        ],
        db_path=db,
    )
    assert created["source"] == "local"
    assert created["is_harbor"] is False
    assert [c["name"] for c in created["criteria"]] == ["a", "b"]
    assert [c["ordinal"] for c in created["criteria"]] == [0, 1]


def test_create_rejects_duplicate_local_name(db: Path):
    with pytest.raises(ConflictError):
        M.create_rubric("l_rubric", "contract", "dup", [], db_path=db)


def test_create_rejects_empty_name(db: Path):
    with pytest.raises(ValidationError):
        M.create_rubric("  ", "contract", "x", [], db_path=db)


def test_create_rejects_criterion_missing_fields(db: Path):
    with pytest.raises(ValidationError):
        M.create_rubric("ok", "contract", "x", [{"name": "a", "description": "", "guidance": "g"}], db_path=db)


# --- update ---------------------------------------------------------------- #


def test_update_local_rubric_keeps_criteria(db: Path):
    updated = M.update_rubric(_local_id(db), "l_renamed", "contract2", "desc2", db_path=db)
    assert updated["name"] == "l_renamed"
    assert [c["name"] for c in updated["criteria"]] == ["c1", "c2"]


def test_update_rejects_harbor(db: Path):
    with pytest.raises(HarborReadOnlyError):
        M.update_rubric(_harbor_id(db), "x", "check", "x", db_path=db)


def test_update_rejects_duplicate_name(db: Path):
    # renaming l_rubric to h_rubric is allowed (different source), but renaming
    # to another LOCAL rubric's name is a conflict - create a second local one.
    M.create_rubric("other_local", "contract", "o", [], db_path=db)
    with pytest.raises(ConflictError):
        M.update_rubric(_local_id(db), "other_local", "contract", "o", db_path=db)


# --- delete ---------------------------------------------------------------- #


def test_delete_local_rubric_cascades(db: Path):
    lid = _local_id(db)
    M.delete_rubric(lid, db_path=db)
    with pytest.raises(NotFoundError):
        M.get_rubric_by_id(lid, db_path=db)
    # criteria are gone too
    conn = sqlite3.connect(db)
    n = conn.execute(
        "SELECT COUNT(*) FROM criteria WHERE rubric_id = ?", (lid,)
    ).fetchone()[0]
    conn.close()
    assert n == 0


def test_delete_rejects_harbor(db: Path):
    with pytest.raises(HarborReadOnlyError):
        M.delete_rubric(_harbor_id(db), db_path=db)


# --- criteria -------------------------------------------------------------- #


def test_add_criterion_appends_at_next_ordinal(db: Path):
    c = M.add_criterion(_local_id(db), "c3", "d3", "g3", db_path=db)
    assert c["ordinal"] == 2
    assert M.get_rubric_detail("l_rubric", db_path=db)["criterion_count"] == 3


def test_add_criterion_rejects_harbor(db: Path):
    with pytest.raises(HarborReadOnlyError):
        M.add_criterion(_harbor_id(db), "x", "d", "g", db_path=db)


def test_add_criterion_rejects_duplicate_name(db: Path):
    with pytest.raises(ConflictError):
        M.add_criterion(_local_id(db), "c1", "d", "g", db_path=db)


def test_update_criterion(db: Path):
    cid = M.get_rubric_detail("l_rubric", db_path=db)["criteria"][0]["id"]
    out = M.update_criterion(cid, "c1_renamed", "newd", "newg", db_path=db)
    assert out["name"] == "c1_renamed"
    assert out["ordinal"] == 0  # unchanged


def test_delete_criterion_renumbers_survivors(db: Path):
    detail = M.get_rubric_detail("l_rubric", db_path=db)
    first, second = detail["criteria"][0], detail["criteria"][1]
    M.delete_criterion(second["id"], db_path=db)
    after = M.get_rubric_detail("l_rubric", db_path=db)["criteria"]
    assert [c["name"] for c in after] == ["c1"]
    assert after[0]["ordinal"] == 0  # renumbered to be contiguous


def test_delete_criterion_rejects_harbor(db: Path):
    hcid = M.get_rubric_detail("h_rubric", db_path=db)["criteria"][0]["id"]
    with pytest.raises(HarborReadOnlyError):
        M.delete_criterion(hcid, db_path=db)


# --- reorder --------------------------------------------------------------- #


def test_reorder_criteria(db: Path):
    detail = M.get_rubric_detail("l_rubric", db_path=db)
    c1, c2 = detail["criteria"][0], detail["criteria"][1]
    M.reorder_criteria(_local_id(db), [c2["id"], c1["id"]], db_path=db)
    after = M.get_rubric_detail("l_rubric", db_path=db)["criteria"]
    assert [c["name"] for c in after] == ["c2", "c1"]
    assert [c["ordinal"] for c in after] == [0, 1]


def test_reorder_rejects_harbor(db: Path):
    hcid = M.get_rubric_detail("h_rubric", db_path=db)["criteria"][0]["id"]
    with pytest.raises(HarborReadOnlyError):
        M.reorder_criteria(_harbor_id(db), [hcid], db_path=db)


def test_reorder_rejects_wrong_id_set(db: Path):
    detail = M.get_rubric_detail("l_rubric", db_path=db)
    c1 = detail["criteria"][0]
    # pass only one of the two ids -> not the full set
    with pytest.raises(ValidationError):
        M.reorder_criteria(_local_id(db), [c1["id"]], db_path=db)


# --- reads ----------------------------------------------------------------- #


def test_list_rubrics_with_counts(db: Path):
    rubrics = {r["name"]: r for r in M.list_rubrics_with_counts(db_path=db)}
    assert rubrics["h_rubric"]["is_harbor"] is True
    assert rubrics["l_rubric"]["is_harbor"] is False
    assert rubrics["h_rubric"]["criterion_count"] == 1
    assert rubrics["l_rubric"]["criterion_count"] == 2


def test_get_rubric_detail_missing(db: Path):
    with pytest.raises(NotFoundError):
        M.get_rubric_detail("nope", db_path=db)


# --- prompts: CRUD --------------------------------------------------------- #


def test_create_prompt(db: Path):
    p = M.create_prompt("p1", "sale", "drafting", "起草买卖合同…", "d", db_path=db)
    assert p["source"] == "local"
    assert p["name"] == "p1"
    assert p["contract_type"] == "sale"
    assert p["purpose"] == "drafting"
    assert p["content"] == "起草买卖合同…"
    assert p["description"] == "d"


def test_create_prompt_rejects_duplicate_name(db: Path):
    M.create_prompt("p1", "sale", "drafting", "x", db_path=db)
    with pytest.raises(ConflictError):
        M.create_prompt("p1", "loan", "drafting", "y", db_path=db)


def test_create_prompt_rejects_empty_fields(db: Path):
    with pytest.raises(ValidationError):
        M.create_prompt("  ", "sale", "drafting", "x", db_path=db)
    with pytest.raises(ValidationError):
        M.create_prompt("p2", "sale", "drafting", "   ", db_path=db)
    with pytest.raises(ValidationError):
        M.create_prompt("p3", "", "drafting", "x", db_path=db)
    with pytest.raises(ValidationError):
        M.create_prompt("p4", "sale", "", "x", db_path=db)


def test_get_prompt_not_found(db: Path):
    with pytest.raises(NotFoundError):
        M.get_prompt("nope", db_path=db)


def test_update_prompt(db: Path):
    p = M.create_prompt("p1", "sale", "drafting", "old", db_path=db)
    updated = M.update_prompt(p["id"], "p1", "loan", "drafting", "new", "d2", db_path=db)
    assert updated["content"] == "new"
    assert updated["contract_type"] == "loan"
    assert updated["description"] == "d2"


def test_update_prompt_rejects_duplicate_name(db: Path):
    M.create_prompt("p1", "sale", "drafting", "x", db_path=db)
    p2 = M.create_prompt("p2", "loan", "drafting", "y", db_path=db)
    with pytest.raises(ConflictError):
        M.update_prompt(p2["id"], "p1", "loan", "drafting", "z", db_path=db)


def test_update_prompt_not_found(db: Path):
    with pytest.raises(NotFoundError):
        M.update_prompt(9999, "x", "sale", "drafting", "y", db_path=db)


def test_delete_prompt(db: Path):
    p = M.create_prompt("p1", "sale", "drafting", "x", db_path=db)
    M.delete_prompt(p["id"], db_path=db)
    with pytest.raises(NotFoundError):
        M.get_prompt("p1", db_path=db)


def test_delete_prompt_not_found(db: Path):
    with pytest.raises(NotFoundError):
        M.delete_prompt(9999, db_path=db)


def test_list_prompts_omits_content(db: Path):
    M.create_prompt("p1", "sale", "drafting", "secret", db_path=db)
    M.create_prompt("p2", "loan", "drafting", "secret2", db_path=db)
    rows = M.list_prompts(db_path=db)
    names = {r["name"] for r in rows}
    assert {"p1", "p2"} <= names
    assert all("content" not in r for r in rows)  # listing omits the body


# --- prompts: schema re-run / harbor writes leave prompts untouched -------- #


def test_create_schema_rerun_leaves_prompts_untouched(db: Path):
    extract = _load_extract_module()
    M.create_prompt("p1", "sale", "drafting", "keep-me", db_path=db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    extract.create_schema(conn)  # idempotent + additive
    conn.close()
    assert M.get_prompt("p1", db_path=db)["content"] == "keep-me"


def test_harbor_upsert_leaves_prompts_untouched(db: Path):
    extract = _load_extract_module()
    M.create_prompt("p1", "sale", "drafting", "keep-me", db_path=db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    # Simulate harbor re-extraction writing a harbor rubric + criteria.
    extract.upsert_harbor_rubric(
        conn,
        {
            "name": "task_quality",
            "context": "check",
            "source_path": "cli/quality_checker/default-rubric.toml",
            "description": "harbor",
        },
        [{"name": "h_c1", "description": "hd", "guidance": "hg", "ordinal": 0}],
        "harbor:v9.9.9",
        "2026-01-01T00:00:00+00:00",
    )
    conn.commit()
    conn.close()
    prompts = M.list_prompts(db_path=db)
    assert len(prompts) == 1
    assert M.get_prompt("p1", db_path=db)["content"] == "keep-me"
