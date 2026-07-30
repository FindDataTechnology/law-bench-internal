"""Persist evaluation runs to the PostgreSQL database (``database_url``).

Adds two tables alongside the existing rubric-definition tables (rubrics /
criteria, which are never touched here):

  eval_runs             - one row per evaluation run: run-level score,
                         all-pass flag, n_passed/n_criteria diagnostics, etc.
  eval_criteria_results - one row per criterion verdict within a run
                         (criterion_id, title, verdict, reasoning, ordinal)

Both mirror harvey-labs' scores.json structure, but relational so runs can be
queried and compared over time. The schema is created idempotently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import connect

RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rubric_name    TEXT NOT NULL,
    contract_path  TEXT,
    task_desc      TEXT,
    score          REAL NOT NULL,
    max_score      REAL NOT NULL,
    all_pass       INTEGER NOT NULL,
    n_criteria     INTEGER NOT NULL,
    n_passed       INTEGER NOT NULL,
    summary        TEXT,
    judge_model    TEXT,
    scored_at      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    compare_run_id INTEGER,
    prompt_name    TEXT,
    prompt_type    TEXT,
    variant_label  TEXT,
    draft_text     TEXT
);

CREATE TABLE IF NOT EXISTS eval_criteria_results (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    criterion_id TEXT NOT NULL,
    title        TEXT,
    verdict      TEXT NOT NULL,
    reasoning    TEXT,
    ordinal      INTEGER NOT NULL,
    UNIQUE(run_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS compare_runs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label         TEXT,
    contract_type TEXT,
    rubric_name   TEXT,
    task_desc     TEXT,
    gen_mode      TEXT,
    n_drafts      INTEGER,
    created_at    TEXT NOT NULL
);
"""

# law_info table (per-contract-type 法律法规 survey answers, one row per
# (contract_type, source)). Created here too so the runtime path establishes it
# even if the seeder's create_schema has not run on this database.
LAW_INFO_SCHEMA = """
CREATE TABLE IF NOT EXISTS law_info (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type TEXT NOT NULL,
    source        TEXT NOT NULL,
    zh_name       TEXT,
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE(contract_type, source)
);
"""

# clauses table (reusable contract clauses extracted from the 示范文本 corpus;
# three categories via the `category` column). Owned by src/clauses, but the DDL
# lives here so ensure_schema establishes it on any database the app touches.
CLAUSES_SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type    TEXT NOT NULL,
    category         TEXT NOT NULL CHECK (category IN ('base','tagged','custom')),
    section          TEXT NOT NULL,
    body             TEXT NOT NULL,
    slot_instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
    law_refs         JSONB NOT NULL DEFAULT '[]'::jsonb,
    level            TEXT CHECK (level IN ('national','local')),
    source_path      TEXT,
    source_doc_title TEXT,
    body_hash        TEXT NOT NULL,
    manual           BOOLEAN NOT NULL DEFAULT false,
    tags             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS clauses_upsert_uk
    ON clauses (source_path, section, body_hash)
    WHERE source_path IS NOT NULL;
"""

# tag_dims table: the controlled-vocabulary tag dimensions (name -> allowed
# values). Populated once per DB by seed_tag_dims (from the per-type manifests)
# and read into the in-memory TAG_VOCAB at app startup, so the running image
# need not ship the seed files. Owned by src/clauses; DDL lives here so
# ensure_schema establishes it on any database the app touches.
TAG_DIMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tag_dims (
    name   TEXT PRIMARY KEY,
    values JSONB NOT NULL
);
"""


# Additive columns added after the tables' first release, applied idempotically
# in a single round trip via ``ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT
# EXISTS`` (a no-op once the columns exist; safe when the table is absent).
_ADDITIVE_COLUMNS = (
    "ALTER TABLE IF EXISTS prompts ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS compare_run_id INTEGER; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_name TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS variant_label TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS draft_text TEXT; "
    "ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS manual BOOLEAN NOT NULL DEFAULT false; "
    "ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '{}'::jsonb; "
    "ALTER TABLE IF EXISTS clauses DROP COLUMN IF EXISTS province;"
)

# The DDL is fully idempotent, so ensure_schema is memoized per database (keyed
# by dbname): the first call on a given DB creates/migrates; subsequent calls
# (every store/list/compare) are a cheap no-op. This matters because the store
# functions call ensure_schema defensively on every invocation.
_ensured_dbs: set[str] = set()


def ensure_schema(db_path=DEFAULT_DB) -> None:
    """Create the results/compare tables if missing and migrate additive columns.

    Idempotent: ``CREATE TABLE IF NOT EXISTS`` for fresh tables, plus
    ``ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS`` for columns added
    after the tables' first release (a no-op once the columns exist). Memoized
    per database so repeated calls are cheap.
    """
    conn = connect(db_path)
    try:
        key = getattr(getattr(conn, "info", None), "dbname", None) or str(db_path)
        if key in _ensured_dbs:
            return
        conn.execute(RESULTS_SCHEMA)
        conn.execute(LAW_INFO_SCHEMA)
        conn.execute(CLAUSES_SCHEMA)
        conn.execute(TAG_DIMS_SCHEMA)
        conn.execute(_ADDITIVE_COLUMNS)
        conn.commit()
        _ensured_dbs.add(key)
    finally:
        conn.close()


def store_result(
    result: dict,
    contract_path: Optional[str] = None,
    task_desc: Optional[str] = None,
    db_path=DEFAULT_DB,
    *,
    compare_run_id: Optional[int] = None,
    prompt_name: Optional[str] = None,
    prompt_type: Optional[str] = None,
    variant_label: Optional[str] = None,
    draft_text: Optional[str] = None,
) -> int:
    """Insert an evaluation run + its per-criterion verdicts. Returns the run id.

    The rubric/contract/task_desc are snapshotted as text so a run survives later
    edits or deletion of the rubric it used. Compare-driven columns
    (``compare_run_id``, ``prompt_name``, ``prompt_type``, ``variant_label``,
    ``draft_text``) are optional keyword-only args; standalone runs leave them
    null, compare runs populate them so the run is grouped under and traceable
    to its prompt without a foreign key.
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO eval_runs "
            "(rubric_name, contract_path, task_desc, score, max_score, all_pass, "
            " n_criteria, n_passed, summary, judge_model, scored_at, created_at, "
            " compare_run_id, prompt_name, prompt_type, variant_label, draft_text) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                result["rubric"],
                contract_path,
                task_desc,
                result["score"],
                result["max_score"],
                int(result["all_pass"]),
                result["n_criteria"],
                result["n_passed"],
                result.get("summary"),
                result.get("judge_model"),
                result.get("scored_at") or now,
                now,
                compare_run_id,
                prompt_name,
                prompt_type,
                variant_label,
                draft_text,
            ),
        )
        run_id = cur.fetchone()["id"]

        for i, c in enumerate(result.get("criteria_results", [])):
            conn.execute(
                "INSERT INTO eval_criteria_results "
                "(run_id, criterion_id, title, verdict, reasoning, ordinal) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (run_id, c["id"], c.get("title"), c["verdict"], c.get("reasoning", ""), i),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()


def list_runs(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent runs (run-level fields only) for quick inspection."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, rubric_name, contract_path, score, all_pass, "
            "       n_passed, n_criteria, judge_model, scored_at "
            "FROM eval_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# --- compare runs ---------------------------------------------------------- #


def store_compare(
    label: Optional[str],
    contract_type: str,
    rubric_name: str,
    task_desc: Optional[str],
    gen_mode: str,
    n_drafts: int,
    db_path=DEFAULT_DB,
) -> int:
    """Insert a ``compare_runs`` row and return its id.

    The returned id is the grouping key passed back as ``compare_run_id`` when
    storing each ``eval_runs`` row that belongs to this compare.
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO compare_runs "
            "(label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, now),
        )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def list_compares(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent compares (compare-level fields only) for the listing view."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, label, contract_type, rubric_name, task_desc, gen_mode, "
            "       n_drafts, created_at "
            "FROM compare_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_compare(compare_id: int, db_path=DEFAULT_DB) -> dict:
    """Full grouped result for one compare: the ``compare_runs`` row, its
    ``eval_runs`` (each with per-criterion verdicts), snapshotted prompt metadata.

    ``draft_text`` is intentionally excluded - it is bulky and fetched lazily via
    ``get_run_draft`` so the default compare payload stays compact.
    """
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        cr = conn.execute(
            "SELECT id, label, contract_type, rubric_name, task_desc, gen_mode, "
            "       n_drafts, created_at FROM compare_runs WHERE id = %s",
            (compare_id,),
        ).fetchone()
        if cr is None:
            raise KeyError(f"Compare not found: {compare_id}")
        runs = conn.execute(
            "SELECT id, rubric_name, contract_path, task_desc, score, max_score, "
            "       all_pass, n_criteria, n_passed, summary, judge_model, scored_at, "
            "       compare_run_id, prompt_name, prompt_type, variant_label "
            "FROM eval_runs WHERE compare_run_id = %s ORDER BY id",
            (compare_id,),
        ).fetchall()
        runs_out = []
        for r in runs:
            crits = conn.execute(
                "SELECT criterion_id, title, verdict, reasoning, ordinal "
                "FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
                (r["id"],),
            ).fetchall()
            runs_out.append({**dict(r), "criteria_results": [dict(c) for c in crits]})
    finally:
        conn.close()
    return {
        "id": cr["id"],
        "label": cr["label"],
        "contract_type": cr["contract_type"],
        "rubric_name": cr["rubric_name"],
        "task_desc": cr["task_desc"],
        "gen_mode": cr["gen_mode"],
        "n_drafts": cr["n_drafts"],
        "created_at": cr["created_at"],
        "runs": runs_out,
    }


def get_run_draft(compare_id: int, run_id: int, db_path=DEFAULT_DB) -> dict:
    """Lazy-fetch a single run's ``draft_text`` (verified to belong to the compare)."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, compare_run_id, prompt_name, draft_text FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(f"Run not found: {run_id}")
    if row["compare_run_id"] != compare_id:
        raise KeyError(f"Run {run_id} does not belong to compare {compare_id}")
    return {
        "run_id": row["id"],
        "prompt_name": row["prompt_name"],
        "draft_text": row["draft_text"],
    }
