"""Project-wide configuration: paths and environment-variable contracts.

Single source of truth for the paths the rest of ``src/`` derives ad hoc:
the repo root, the evaluation-rules SQLite DB, the contract templates dir,
and the harbor extraction script. Also defines the required-env-var lists
used by the drafting crew and the evaluation judge, and the ``ConfigError``
raised when a required env var is missing.

Named ``settings.py`` (not ``config.py``) because ``src/config/`` already
exists as the CrewAI YAML data directory - a ``config.py`` file beside a
``config/`` package would be import-ambiguous.
"""

from __future__ import annotations

from pathlib import Path

# src/settings.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

# SQLite DB shared by the evaluation engine and the web layer.
DEFAULT_DB = REPO_ROOT / "db" / "evaluation_rules.db"

# Seed contract templates loaded into the drafter's context.
TEMPLATES_DIR = REPO_ROOT / "templates"

# Harbor extraction script (single source of truth for the rubric schema).
EXTRACT_SCRIPT = REPO_ROOT / "scripts" / "extract_harbor_rules.py"

# LLM contract-template regeneration script (mode G): rewrites the global
# ``src/contracts/data/contracts.json`` 母版 bodies via the DRAFTER LLM.
GENERATE_TEMPLATES_SCRIPT = REPO_ROOT / "scripts" / "generate_contract_templates_llm.py"


class ConfigError(Exception):
    """A required environment variable is missing or misconfigured."""


# Env vars the drafting crew needs (checked up front in main.py / llm.py).
DRAFTING_REQUIRED_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "INTAKE_MODEL",
    "DRAFTER_MODEL",
    "AUDITOR_MODEL",
]

# Env vars the evaluation judge needs (checked in judge.py).
EVAL_JUDGE_REQUIRED_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "EVAL_MODEL",
]


# --------------------------------------------------------------------------- #
# Search / RAG service config (read from env; used by src/search/*)
# --------------------------------------------------------------------------- #

import os as _os
from urllib.parse import urlparse as _urlparse

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return _os.environ.get(key, default)


# PostgreSQL DSN (single source of truth for the relational layer).
DATABASE_URL = _env("database_url") or _env("DATABASE_URL")

# Embeddings via OpenRouter (OpenAI-compatible /embeddings endpoint).
OPENROUTER_API_BASE = _env("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY", "")
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b:free")
EMBEDDING_DIMS = int(_env("EMBEDDING_DIMS", "2048"))

# Elasticsearch vector store.
ES_URL = _env("elastic_search_host", "")
ES_USER = _env("elastic_search_user", "elastic")
ES_PASSWORD = _env("elastic_search_pass", "")
SEARCH_INDEX_NAME = _env("SEARCH_INDEX_NAME", "contracts")

# MinIO document source (S3-compatible). minio_host is a full URL; the reader
# wants host:port + a secure flag.
_minio_host_full = _env("minio_host", "http://localhost:9000")
MINIO_SECURE = _minio_host_full.startswith("https")
MINIO_ENDPOINT = _urlparse(_minio_host_full).netloc  # host:port
MINIO_ACCESS_KEY = _env("minio_root_user", "")
MINIO_SECRET_KEY = _env("minio_root_password", "")
MINIO_BUCKET = _env("MINIO_BUCKET", "scraw-law-contracts")
MINIO_TEMPLATES_PREFIX = _env("MINIO_TEMPLATES_PREFIX", "templates/")
MINIO_DRAFTS_PREFIX = _env("MINIO_DRAFTS_PREFIX", "drafts/")
# Generated contract docx/pdf (artifacts) are stored under this prefix.
MINIO_ARTIFACTS_PREFIX = _env("MINIO_ARTIFACTS_PREFIX", "artifacts/")

# CrewAI RAG retrieval tool toggle (on by default; degrades gracefully if off).
RAG_TOOL_ENABLED = _env("RAG_TOOL_ENABLED", "1") == "1"

# Search-service env vars required for live RAG (checked up front where useful).
SEARCH_REQUIRED_VARS = [
    "database_url",
    "OPENROUTER_API_KEY",
    "elastic_search_host",
    "elastic_search_pass",
    "minio_host",
    "minio_root_password",
]


# --------------------------------------------------------------------------- #
# Auth config (Phase 2 — Logto hybrid Cookie + APIKey)
# --------------------------------------------------------------------------- #
# Identity is fully delegated to a self-deployed Logto instance (OIDC). This
# project stores NO passwords and has NO local users table. Browser sessions
# use the OIDC authorization-code flow -> signed httpOnly cookie; programmatic
# callers use either a Logto-issued Bearer JWT (JWKS-validated) or a
# self-managed X-API-Key (salted hash in the ``api_keys`` table).

# Logto OIDC endpoint (base URL, e.g. https://logto.example.com). Trailing
# slash stripped so ``LOGTO_ENDPOINT + "/oidc/..."`` composes cleanly.
LOGTO_ENDPOINT = _env("LOGTO_ENDPOINT", "").rstrip("/")
LOGTO_CLIENT_ID = _env("LOGTO_CLIENT_ID", "")
LOGTO_CLIENT_SECRET = _env("LOGTO_CLIENT_SECRET", "")
# Absolute public URL the IdP redirects to after authorize (-> /auth/callback).
LOGTO_REDIRECT_URI = _env("LOGTO_REDIRECT_URI", "")
# Public base URL of this app (e.g. https://lawbench.example.com). Used only as
# the OIDC post-logout redirect target so the IdP can send the browser back here
# after ending its session. When empty, logout clears the cookie locally and
# redirects to "/" without calling the IdP end-session endpoint.
APP_BASE_URL = _env("APP_BASE_URL", "").rstrip("/")
# OIDC scopes requested at the authorize step.
LOGTO_SCOPES = _env("LOGTO_SCOPES", "openid profile email").split()

# Optional: the Logto API-resource indicator that Bearer access-token JWTs are
# minted for. When set, Bearer JWTs are audience-checked against it. When empty,
# audience verification is skipped (issuer + signature + exp still enforced) —
# acceptable only for a single-resource self-deploy; set it in prod to bind
# tokens to this API. Defaults to the client_id so ID-token-style bearers also
# validate.
LOGTO_API_AUDIENCE = _env("LOGTO_API_AUDIENCE", LOGTO_CLIENT_ID)

# Session cookie signing secret. MUST be a stable deploy secret — never
# auto-generated per restart; rotating it invalidates every live session and
# there is no key-rotation path here, so treat it as a permanent deploy secret.
AUTH_SESSION_SECRET = _env("AUTH_SESSION_SECRET", "")
# Session cookie lifetime in seconds (default: 7 days).
AUTH_SESSION_TTL = int(_env("AUTH_SESSION_TTL", str(7 * 24 * 3600)))
# Cookie attributes. AUTH_COOKIE_SECURE=0 allows http on localhost for dev;
# leave 1 in prod (Secure requires https). httpOnly + SameSite=Lax are fixed.
AUTH_COOKIE_NAME = _env("AUTH_COOKIE_NAME", "lawbench_session")
AUTH_COOKIE_SECURE = _env("AUTH_COOKIE_SECURE", "1") == "1"

# Env vars that MUST be populated before the app serves any traffic. Checked
# fail-fast at startup in create_app() — a missing value means the process
# refuses to boot (fail closed: never run an open server). JWKS reachability
# is validated separately in the auth package (also fail-closed).
AUTH_REQUIRED_VARS = [
    "LOGTO_ENDPOINT",
    "LOGTO_CLIENT_ID",
    "LOGTO_CLIENT_SECRET",
    "LOGTO_REDIRECT_URI",
    "AUTH_SESSION_SECRET",
]


def check_auth_config() -> None:
    """Raise :class:`ConfigError` if any required auth env var is unset.

    Called from ``create_app()`` at startup so the process fails closed — no
    auth config, no server. Only checks *presence* of the values; reachability
    of the Logto endpoint / JWKS is validated in :mod:`src.web.auth.logto`.
    """
    missing = [name for name in AUTH_REQUIRED_VARS if not _env(name)]
    if missing:
        raise ConfigError(
            "Auth is not configured — refusing to start. "
            "Set these env vars: " + ", ".join(missing)
        )
