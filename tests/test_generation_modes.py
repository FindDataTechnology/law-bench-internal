"""Tests for the contract-generation mode routes (``src/web/routes/generation.py``).

Covers:
- store-layer ``generation_jobs`` CRUD round-trip (store -> update -> get / list)
- mode D sync batch generation (one combo, markdown to avoid file I/O)
- modes E/F/G async submit (202 + poll) with the background task stubbed so no
  LLM / subprocess / langgraph dependency is exercised
- error paths: 404 unknown type, 400 mode mismatch, 400 missing tag_combinations,
  404 unknown job id
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from src.clauses.store import upsert_clause
from src.eval.store import (
    get_generation_job,
    list_generation_jobs,
    store_generation_job,
    update_generation_job,
)


# --- seeding helpers (minimal copies of test_contract_context_api) -------- #


def _seed_base(seeded_db) -> None:
    """One base clause covering 当事人 - enough for assembly to succeed."""
    upsert_clause(
        {
            "id": 1,
            "contract_type": "sale",
            "category": "base",
            "section": "当事人",
            "body": "甲方：{{party_a}}\n乙方：{{party_b}}",
            "slot_instructions": [
                {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True},
                {"name": "party_b", "label": "乙方", "description": "d", "example": "x", "required": True},
            ],
            "law_refs": [],
            "level": "national",
            "source_path": "t/base.docx",
            "source_doc_title": "T",
            "body_hash": "h-base-当事人",
            "tags": {"source": "base"},
        },
        db=seeded_db,
    )


# --- store-layer CRUD ----------------------------------------------------- #


def test_job_crud_round_trip(seeded_db):
    jid = store_generation_job("pipeline", "sale", db_path=seeded_db)
    assert isinstance(jid, int)

    row = get_generation_job(jid, db_path=seeded_db)
    assert row["kind"] == "pipeline"
    assert row["contract_type"] == "sale"
    assert row["status"] == "pending"
    assert row["result_ref"] is None
    assert row["error_message"] is None

    update_generation_job(jid, status="running", db_path=seeded_db)
    update_generation_job(
        jid,
        status="completed",
        result_ref={"score": 3, "n_criteria": 3, "all_pass": True},
        db_path=seeded_db,
    )
    row = get_generation_job(jid, db_path=seeded_db)
    assert row["status"] == "completed"
    assert json.loads(row["result_ref"])["all_pass"] is True

    rows = list_generation_jobs(limit=10, db_path=seeded_db)
    assert any(r["id"] == jid for r in rows)


def test_job_failed_round_trip(seeded_db):
    jid = store_generation_job("regenerate", "sale", db_path=seeded_db)
    update_generation_job(
        jid, status="failed", error_message="boom", db_path=seeded_db
    )
    row = get_generation_job(jid, db_path=seeded_db)
    assert row["status"] == "failed"
    assert row["error_message"] == "boom"
    assert row["result_ref"] is None


def test_get_missing_job_returns_none(seeded_db):
    assert get_generation_job(999999999, db_path=seeded_db) is None


# --- mode D: sync batch --------------------------------------------------- #


def test_generate_batch_one_combo(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    r = app_client.post(
        "/api/contracts/sale/generate-batch",
        json={
            "mode": "D",
            "tag_combinations": [{"stance": "balanced"}],
            "format": "markdown",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contract_type"] == "sale"
    assert body["total_requested"] == 1
    assert body["success_count"] == 1
    assert body["failure_count"] == 0
    res = body["results"][0]
    assert res["success"] is True
    assert res["body_text"]
    assert res["tags"] == {"stance": "balanced"}


# --- modes E/F/G: async submit + poll (background task stubbed) ---------- #
#
# Starlette's TestClient runs BackgroundTasks synchronously and waits for them
# to complete before the request method returns, so by the time we GET the job
# the stub has already flipped it to a terminal status. The poll loop below is
# defensive: it also covers any future async-client behavior.


def _stub_self_heal(job_id, contract_type, body, db_path):
    update_generation_job(job_id, status="running", db_path=db_path)
    update_generation_job(
        job_id,
        status="completed",
        result_ref={
            "pipeline_run_id": 1,
            "score": 3,
            "n_criteria": 3,
            "n_passed": 3,
            "all_pass": True,
            "iteration": 1,
            "eval_run_id": 99,
        },
        db_path=db_path,
    )


def _stub_auto_reject(job_id, contract_type, body, db_path):
    update_generation_job(job_id, status="running", db_path=db_path)
    update_generation_job(
        job_id,
        status="completed",
        result_ref={
            "pipeline_run_id": 2,
            "score": 3,
            "all_pass": True,
            "iteration": 1,
            "learn_applied": 1,
        },
        db_path=db_path,
    )


def _stub_regenerate(job_id, contract_type, db_path):
    update_generation_job(job_id, status="running", db_path=db_path)
    update_generation_job(
        job_id,
        status="completed",
        result_ref={"returncode": 0, "stdout": "regenerated", "stderr": ""},
        db_path=db_path,
    )


def _poll_job(app_client: TestClient, job_id: int, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = app_client.get(f"/api/generation-jobs/{job_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in ("completed", "failed"):
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached terminal status (last={last})")


def test_submit_pipeline_async(app_client: TestClient, monkeypatch, seeded_db):
    monkeypatch.setattr("src.web.routes.generation._run_self_heal", _stub_self_heal)
    r = app_client.post(
        "/api/contracts/sale/pipeline",
        json={"mode": "E", "max_iterations": 1, "format": "markdown"},
    )
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "pending"
    job_id = data["job_id"]

    job = _poll_job(app_client, job_id)
    assert job["kind"] == "pipeline"
    assert job["contract_type"] == "sale"
    assert job["status"] == "completed"
    assert job["result_ref"]["all_pass"] is True
    assert job["result_ref"]["iteration"] == 1
    assert job["error_message"] is None


def test_submit_auto_reject_async(app_client: TestClient, monkeypatch, seeded_db):
    monkeypatch.setattr("src.web.routes.generation._run_auto_reject", _stub_auto_reject)
    r = app_client.post(
        "/api/contracts/sale/auto-reject",
        json={"mode": "F", "max_iterations": 1, "format": "markdown"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = _poll_job(app_client, job_id)
    assert job["kind"] == "auto_reject"
    assert job["status"] == "completed"
    assert job["result_ref"]["learn_applied"] == 1


def test_submit_regenerate_async(app_client: TestClient, monkeypatch, seeded_db):
    monkeypatch.setattr("src.web.routes.generation._run_regenerate", _stub_regenerate)
    r = app_client.post(
        "/api/contracts/sale/regenerate-template",
        json={"mode": "G"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = _poll_job(app_client, job_id)
    assert job["kind"] == "regenerate"
    assert job["status"] == "completed"
    assert job["result_ref"]["returncode"] == 0
    assert job["result_ref"]["stdout"] == "regenerated"


def test_list_jobs_after_submit(app_client: TestClient, monkeypatch, seeded_db):
    monkeypatch.setattr("src.web.routes.generation._run_self_heal", _stub_self_heal)
    app_client.post(
        "/api/contracts/sale/pipeline", json={"mode": "E", "format": "markdown"}
    )
    r = app_client.get("/api/generation-jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert jobs  # at least the one we just submitted
    j = jobs[0]
    assert j["kind"] == "pipeline"
    # result_ref is parsed (dict) for a completed job, None while pending.
    assert isinstance(j["result_ref"], (dict, type(None)))


# --- error paths ---------------------------------------------------------- #


def test_get_job_unknown_404(app_client: TestClient):
    assert app_client.get("/api/generation-jobs/999999999").status_code == 404


def test_unknown_type_404(app_client: TestClient):
    for path in ("generate-batch", "pipeline", "auto-reject", "regenerate-template"):
        r = app_client.post(
            f"/api/contracts/does_not_exist/{path}", json={"format": "markdown"}
        )
        assert r.status_code == 404, path


def test_mode_mismatch_400(app_client: TestClient, seeded_db):
    # mode D route receives mode=E -> 400 (before any work)
    r = app_client.post(
        "/api/contracts/sale/generate-batch",
        json={
            "mode": "E",
            "tag_combinations": [{"stance": "balanced"}],
            "format": "markdown",
        },
    )
    assert r.status_code == 400
    # mode E route receives mode=D -> 400 (before the job row is inserted)
    r = app_client.post(
        "/api/contracts/sale/pipeline", json={"mode": "D", "format": "markdown"}
    )
    assert r.status_code == 400
    # a mismatched submit must not leave a job row behind
    assert app_client.get("/api/generation-jobs").json() == []


def test_batch_missing_combos_400(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    # neither enumerate_all nor tag_combinations -> 400
    r = app_client.post(
        "/api/contracts/sale/generate-batch", json={"format": "markdown"}
    )
    assert r.status_code == 400
    assert "tag_combinations" in r.json()["detail"]
