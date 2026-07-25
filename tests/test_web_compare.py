"""Web API tests for /api/compare and prompt_type on /api/prompts.

Run against a throwaway DB via the ``app_client`` fixture. ``run_compare`` is
monkeypatched so POST stays hermetic (no DRAFTER LLM, no judge endpoint); the
read endpoints exercise the real store layer against the throwaway DB.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.eval.store import (
    get_compare,
    store_compare,
    store_result,
)
from src.web.routes import api as api_module

_PREFIX = "__cmp_"


def _result(rubric="contract_sale_v1", verdicts=(("party_id", "pass"), ("price", "fail"))):
    return {
        "rubric": rubric,
        "score": 0.0,
        "max_score": 1.0,
        "all_pass": False,
        "n_criteria": len(verdicts),
        "n_passed": sum(1 for _, v in verdicts if v == "pass"),
        "summary": "s",
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
        "criteria_results": [
            {"id": cid, "title": f"t-{cid}", "verdict": v, "reasoning": "r"}
            for cid, v in verdicts
        ],
    }


def test_list_compares_empty(app_client: TestClient):
    r = app_client.get("/api/compare")
    assert r.status_code == 200
    assert r.json() == []


def test_get_compare_unknown_returns_404(app_client: TestClient):
    assert app_client.get("/api/compare/9999").status_code == 404


def _seed_compare(db_path) -> tuple[int, int]:
    """Seed a real compare row + one run (with draft_text) directly in the store."""
    cid = store_compare("sale test", "sale", "contract_sale_v1", "task",
                        "drafter-only", 1, db_path=db_path)
    rid = store_result(
        _result(), task_desc="task", db_path=db_path,
        compare_run_id=cid, prompt_name="draft_sale", prompt_type="baseline",
        variant_label="baseline", draft_text="THE DRAFT",
    )
    return cid, rid


def test_get_compare_returns_matrix_without_draft(app_client: TestClient, seeded_db):
    cid, _ = _seed_compare(seeded_db)
    r = app_client.get(f"/api/compare/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cid
    assert "matrix" in body
    assert body["matrix"]["columns"][0]["prompt_type"] == "baseline"
    assert "draft_text" not in body["runs"][0]


def test_get_run_draft_lazy(app_client: TestClient, seeded_db):
    cid, rid = _seed_compare(seeded_db)
    r = app_client.get(f"/api/compare/{cid}/run/{rid}/draft")
    assert r.status_code == 200
    assert r.json()["draft_text"] == "THE DRAFT"


def test_get_run_draft_wrong_compare_404(app_client: TestClient, seeded_db):
    cid, rid = _seed_compare(seeded_db)
    # rid belongs to cid; asking under a different compare id -> 404
    assert app_client.get(f"/api/compare/{cid + 999}/run/{rid}/draft").status_code == 404


def test_post_compare_delegates_to_run_compare(app_client: TestClient, seeded_db, monkeypatch):
    """POST /api/compare parses the body, resolves prompts, and returns run_compare's output."""
    captured = {}

    def fake_load_prompts(names, db_path=None):
        captured["names"] = list(names)
        return [{"name": n, "content": "c", "prompt_type": "baseline"} for n in names]

    def fake_run_compare(contract_type, rubric_name, task_desc, prompts, mode="drafter-only",
                         n_drafts=1, label=None, db_path=None, **kw):
        captured.update(contract_type=contract_type, rubric_name=rubric_name,
                        task_desc=task_desc, mode=mode, n_drafts=n_drafts,
                        n_prompts=len(prompts))
        cid = store_compare(label or "lbl", contract_type, rubric_name, task_desc,
                            mode, n_drafts, db_path=db_path)
        store_result(_result(), task_desc=task_desc, db_path=db_path,
                     compare_run_id=cid, prompt_name=prompts[0]["name"],
                     prompt_type="baseline", variant_label="baseline", draft_text="D")
        return get_compare(cid, db_path=db_path)

    monkeypatch.setattr(api_module, "load_prompts", fake_load_prompts)
    monkeypatch.setattr(api_module, "run_compare", fake_run_compare)

    r = app_client.post("/api/compare", json={
        "contract_type": "sale",
        "rubric_name": "contract_sale_v1",
        "task_desc": "起草一份买卖合同",
        "prompts": ["draft_sale", "draft_sale_v2"],
        "mode": "drafter-only",
        "n_drafts": 1,
        "label": "my compare",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contract_type"] == "sale"
    assert "matrix" in body
    assert captured["names"] == ["draft_sale", "draft_sale_v2"]
    assert captured["n_prompts"] == 2


def test_post_compare_missing_prompt_returns_404(app_client: TestClient, monkeypatch):
    # load_prompts is NOT patched -> real lookup raises NotFoundError -> 404.
    r = app_client.post("/api/compare", json={
        "contract_type": "sale", "rubric_name": "contract_sale_v1",
        "task_desc": "t", "prompts": ["__nope1__", "__nope2__"],
    })
    assert r.status_code == 404


# --- prompt_type on /api/prompts ------------------------------------------ #


def test_prompt_create_with_type_round_trip(app_client: TestClient):
    name = _PREFIX + "typed"
    r = app_client.post("/api/prompts", json={
        "name": name, "contract_type": "sale", "purpose": "drafting",
        "content": "c", "prompt_type": "experimental",
    })
    assert r.status_code == 201
    assert r.json()["prompt_type"] == "experimental"

    r = app_client.get(f"/api/prompts/{name}")
    assert r.json()["prompt_type"] == "experimental"


def test_prompt_create_blank_type_allowed(app_client: TestClient):
    name = _PREFIX + "notype"
    r = app_client.post("/api/prompts", json={
        "name": name, "contract_type": "sale", "purpose": "drafting", "content": "c",
    })
    assert r.status_code == 201
    assert r.json()["prompt_type"] is None


def test_prompt_update_changes_type(app_client: TestClient):
    name = _PREFIX + "updtype"
    app_client.post("/api/prompts", json={
        "name": name, "contract_type": "sale", "purpose": "drafting",
        "content": "c", "prompt_type": "experimental",
    })
    r = app_client.patch(f"/api/prompts/{name}", json={
        "name": name, "contract_type": "sale", "purpose": "drafting",
        "content": "c", "prompt_type": "improved",
    })
    assert r.status_code == 200
    assert r.json()["prompt_type"] == "improved"
