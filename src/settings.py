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
