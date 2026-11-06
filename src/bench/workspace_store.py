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
"""
