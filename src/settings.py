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
