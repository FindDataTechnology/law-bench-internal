"""Idempotent DDL for the workspace data layer (domain-neutral kernel).

Six tables back the template/domain/membership/invitation records and the
authoring surface (change events + work tasks). The DDL follows the kernel
convention: ``CREATE TABLE IF NOT EXISTS`` constants that
``src.eval.store.ensure_schema`` executes on first connect, right next to
``BENCH_SCHEMA``. There is no migration framework in this repository, so every
statement here must stay idempotent.

Vocabulary and comments in this module are deliberately generic: the kernel
does not know which verticals instantiate these records.

Notes on the shape:

- ``ontology_templates`` is append-only by version: an edit inserts a new row
  with a higher version, it never rewrites a historical row.
- ``domains`` anchors the exact template row (id) and version it was created
  from, so later versions do not retroactively change an existing domain.
- ``domain_members`` is append-only history: a role change retires the active
  row (``removed_at``) and inserts a fresh one. A partial unique index keeps at
  most one active row per (domain, user); plain history rows are unrestricted.
- ``domain_invitations`` stores only a digest of the credential, never the
  plaintext value.
- ``authoring_events`` is append-only: no UPDATE/DELETE paths exist by design
  (the change trail must stay replayable).
- ``ontology_publications`` is append-only: a publication freezes one immutable
  versioned snapshot of a domain's content (manifest + changelog JSONB). No
  UPDATE/DELETE code paths exist by design — historical snapshots must stay
  byte-identical forever; new content means a new version row.
- ``distribution_consumers`` registers machine pull credentials: only the
  credential digest is stored (never a plaintext token), and revocation is a
  soft flag (``revoked_at``) that the lookup layer treats as fail-closed.
- ``rag_corpora`` registers the retrieval corpus of a workspace: one row per
  domain (``domain_id`` UNIQUE) naming the search index it owns (``index_name``
  UNIQUE, so two workspaces can never point at one index), the source
  declarations (JSONB list of {bucket, prefix} objects; empty = no sources
  configured), and an optional embedding-model declaration (NULL = the global
  default). Re-registration replaces the row via upsert; ownership of a row
  never changes domain.
- The C5 console tables (change ``add-domain-first-workbench``) are additive and
  keep the same discipline: ``domain_members.last_opened_at`` is a per-user
  navigation hint (not content, not audit); ``domain_assets`` is a many-to-many
  directory over heterogeneous pre-existing asset tables (no FK, never touches
  the asset); ``domain_proposals`` is a submission snapshot + workflow state
  (never a second ontology store; confirmation goes through the kernel upsert);
  ``domain_proposal_events`` and ``distribution_pull_events`` are append-only
  trails with no UPDATE/DELETE path.
"""

from __future__ import annotations

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_templates (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    schema      JSONB NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS domains (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key               TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    template_id       BIGINT NOT NULL REFERENCES ontology_templates(id),
    template_version  INTEGER NOT NULL,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain_members (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    added_by    TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS domain_members_active_uk
    ON domain_members (domain_id, user_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS domain_members_domain_idx
    ON domain_members (domain_id);

CREATE TABLE IF NOT EXISTS domain_invitations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id    BIGINT NOT NULL REFERENCES domains(id),
    role         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    invited_by   TEXT NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at  TIMESTAMPTZ,
    accepted_by  TEXT
);

CREATE TABLE IF NOT EXISTS authoring_events (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id  BIGINT NOT NULL REFERENCES domains(id),
    unit_kind  TEXT NOT NULL,
    unit_key   TEXT NOT NULL,
    op         TEXT NOT NULL CHECK (op IN ('create','update','delete')),
    before     JSONB,
    after      JSONB,
    operator   TEXT NOT NULL,
    via        TEXT NOT NULL DEFAULT 'authoring',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS authoring_events_unit_idx
    ON authoring_events (domain_id, unit_kind, unit_key);
CREATE INDEX IF NOT EXISTS authoring_events_created_idx
    ON authoring_events (domain_id, created_at);

CREATE TABLE IF NOT EXISTS authoring_tasks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    assignee    TEXT NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    target_kind TEXT,
    target_key  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','in_progress','done','cancelled')),
    transitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS authoring_tasks_assignee_idx
    ON authoring_tasks (domain_id, assignee);
CREATE INDEX IF NOT EXISTS authoring_tasks_status_idx
    ON authoring_tasks (domain_id, status);

-- Append-only by design: no UPDATE/DELETE code paths exist for publications
-- (a published snapshot must stay byte-identical forever; new content is a
-- new version row, never a rewrite).
CREATE TABLE IF NOT EXISTS ontology_publications (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id    BIGINT NOT NULL REFERENCES domains(id),
    version      INTEGER NOT NULL,
    digest       TEXT NOT NULL,
    manifest     JSONB NOT NULL,
    changelog    JSONB NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain_id, version),
    UNIQUE (domain_id, digest)
);
CREATE INDEX IF NOT EXISTS ontology_publications_domain_idx
    ON ontology_publications (domain_id);

CREATE TABLE IF NOT EXISTS distribution_consumers (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    domains    TEXT[] NOT NULL DEFAULT '{}',
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rag_corpora (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id       BIGINT NOT NULL UNIQUE REFERENCES domains(id),
    index_name      TEXT NOT NULL UNIQUE,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding_model TEXT,
    registered_by   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- C5 add-domain-first-workbench -------------------------------------------------
-- last_opened_at: the domain list orders by this user's own recency. It is a
-- per-user navigation hint, never content or an audit record; a removed
-- membership keeps its timestamp (the partial unique index already guarantees
-- at most one ACTIVE row per (domain, user)).
ALTER TABLE IF EXISTS domain_members
    ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ;

-- domain_assets: the domain's catalog of evaluation assets (rubrics, prompts,
-- compare sets, samples, clauses, law_info ...). Pure directory semantics:
-- many-to-many, and NO change to any asset table's shape or behaviour. A row
-- is a claim "this asset belongs in this domain's shelf", not ownership;
-- unassigning never touches the asset itself. asset_key is the asset's own
-- stable textual identifier (name / slug / id as text), never a FK, because
-- the asset tables are heterogeneous and predate domains.
CREATE TABLE IF NOT EXISTS domain_assets (
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    asset_kind  TEXT NOT NULL,
    asset_key   TEXT NOT NULL,
    added_by    TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_id, asset_kind, asset_key)
);
CREATE INDEX IF NOT EXISTS domain_assets_asset_idx
    ON domain_assets (asset_kind, asset_key);

-- domain_proposals: the domain's proposal inbox (blueprint C5). A proposal is a
-- SUBMISSION SNAPSHOT plus its workflow state — it is never a second ontology
-- store and never participates in retrieval. Confirmation goes through the one
-- kernel write path (authoring upsert), so the KU table stays the only content
-- truth. The partial unique index is the idempotency rule: at most one PENDING
-- proposal per (domain, source, external_key); a rejected proposal stays on
-- record and a resubmission is only accepted with a different evidence_digest.
CREATE TABLE IF NOT EXISTS domain_proposals (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id       BIGINT NOT NULL REFERENCES domains(id),
    source          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    external_key    TEXT NOT NULL,
    body            TEXT NOT NULL,
    evidence        JSONB NOT NULL,
    evidence_digest TEXT NOT NULL,
    impact          TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'confirmed', 'rejected')),
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    decision_note   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS domain_proposals_pending_uk
    ON domain_proposals (domain_id, source, external_key) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS domain_proposals_box_idx
    ON domain_proposals (domain_id, state, submitted_at DESC);

-- domain_proposal_events: append-only state trail (submit / confirm / reject).
-- No UPDATE or DELETE path may exist by design, same discipline as
-- authoring_events: the workflow history must stay replayable.
CREATE TABLE IF NOT EXISTS domain_proposal_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id BIGINT NOT NULL REFERENCES domain_proposals(id),
    from_state  TEXT,
    to_state    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS domain_proposal_events_proposal_idx
    ON domain_proposal_events (proposal_id, happened_at);

-- distribution_pull_events: append-only pull trail. The consumer row stays
-- untouched (no last_used_at column, no update contention); the ledger derives
-- "latest pull" per consumer from this table. Only successful pulls that
-- resolved a publication are recorded — a rejected credential or a 404 pull
-- leaves no event, so the trail never claims a pull that did not happen.
CREATE TABLE IF NOT EXISTS distribution_pull_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consumer_id BIGINT NOT NULL REFERENCES distribution_consumers(id),
    domain_key  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS distribution_pull_events_consumer_idx
    ON distribution_pull_events (consumer_id, happened_at DESC);

-- domain_agent_runs: 每轮智能体运行一行。这是"昨晚干了什么"的唯一答案，也是
-- `thin` 与 `failed` 必须分开的地方——前者升级给人，后者不得用重试掩盖。
--
-- 刻意不存推理过程：存的是**可复算的输入摘要 + 计数 + 产物引用**。运行结论文本
-- 没有审计价值，反而会诱使后来者把它当证据。`remaining` 单独成列，是因为
-- "批次不收敛"是实测过的失败模式，必须能被机械检测（见 src/bench/agent_runs.py）。
CREATE TABLE IF NOT EXISTS domain_agent_runs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role          TEXT NOT NULL,
    domain_key    TEXT NOT NULL,
    task_id       BIGINT REFERENCES authoring_tasks(id),
    run_key       TEXT,
    outcome       TEXT NOT NULL DEFAULT 'running'
                  CHECK (outcome IN ('running','ok','thin','failed','stopped')),
    input_digest  TEXT,
    counts        JSONB NOT NULL DEFAULT '{}'::jsonb,
    remaining     BIGINT,
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    detail        TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS domain_agent_runs_domain_idx
    ON domain_agent_runs (domain_key, started_at DESC);
CREATE INDEX IF NOT EXISTS domain_agent_runs_outcome_idx
    ON domain_agent_runs (domain_key, outcome, started_at DESC);

-- 名字必须带域前缀：这个库是**多产品共用**的，`agent_runs` 这个泛名已被另一个
-- 产品线的同名表占用（字段是 thread/节点耗时/评分那一套，实测 23 行）。
-- `CREATE TABLE IF NOT EXISTS` 遇到
-- 同名旧表会静默跳过，随后给不存在的列建索引就会在**启动期**炸掉整个进程
-- （2026-11-09 实际发生，pod CrashLoopBackOff）。所以：不共用泛名，也不在启动期
-- 加断言——启动期抛异常本身就是那次事故的形态。
"""
