"""Versioned ontology-template records: structural validation + CRUD.

A template is a versioned, append-only JSONB record: creating one writes
version 1, and every edit inserts a new row with ``max(version) + 1`` instead
of rewriting a historical row. The schema's controlled vocabularies are
checked against the kernel's single sources of truth so a structurally
incomplete template can neither be stored nor used to open a domain.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Rows are decoded from either dict-row or
plain tuple cursors, and JSONB is encoded/decoded with ``json.dumps``/
``json.loads``.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .promotion import SENSITIVITY_LEVELS
from .tiers import TIERS

REQUIRED_SCHEMA_KEYS = (
    "entity_types",
    "concept_structures",
    "relationship_kinds",
    "tier_vocabulary",
    "sensitivity_vocabulary",
    "corpus_declaration",
)

_TEMPLATE_COLS = "id, name, version, schema, created_by, created_at"
_TEMPLATE_KEYS = ("id", "name", "version", "schema", "created_by", "created_at")
_LIST_KEYS = (
    "entity_types",
    "relationship_kinds",
    "tier_vocabulary",
    "sensitivity_vocabulary",
)


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _scalar(row: Any) -> Any:
    """First value of an aggregate row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _row_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _TEMPLATE_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "name": values[1],
        "version": values[2],
        "schema": _decode_jsonb(values[3]),
        "created_by": values[4],
        "created_at": _iso(values[5]),
    }


def validate_template_schema(schema: dict) -> list[str]:
    """Return the list of structural problems; an empty list means valid.

    Checks the required keys, the shape of the four controlled vocabularies and
    the two declaration objects, and equality of the tier/sensitivity
    vocabularies with the kernel's canonical tuples. This is a pure function:
    it needs no connection.
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return ["schema must be a dict"]

    for key in REQUIRED_SCHEMA_KEYS:
        if key not in schema:
            problems.append(f"missing required key: {key}")

    for key in _LIST_KEYS:
        if key not in schema:
            continue
        value = schema[key]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) for item in value)
        ):
            problems.append(f"{key} must be a non-empty list of strings")

    for key in ("concept_structures", "corpus_declaration"):
        if key in schema and not isinstance(schema[key], dict):
            problems.append(f"{key} must be a dict")

    tier_vocab = schema.get("tier_vocabulary")
    if isinstance(tier_vocab, list) and all(isinstance(v, str) for v in tier_vocab):
        if set(tier_vocab) != set(TIERS):
            problems.append(
                "tier_vocabulary must equal the platform vocabulary "
                f"{list(TIERS)}"
            )
    sensitivity_vocab = schema.get("sensitivity_vocabulary")
    if isinstance(sensitivity_vocab, list) and all(
        isinstance(v, str) for v in sensitivity_vocab
    ):
        if set(sensitivity_vocab) != set(SENSITIVITY_LEVELS):
            problems.append(
                "sensitivity_vocabulary must equal the platform vocabulary "
                f"{list(SENSITIVITY_LEVELS)}"
            )
    return problems


def create_template(conn: Any, *, name: str, schema: dict, created_by: str) -> dict:
    """Insert version 1 of a new template; duplicate names are refused."""
    if not name:
        raise ValueError("name is required")
    problems = validate_template_schema(schema)
    if problems:
        raise ValueError("; ".join(problems))
    existing = conn.execute(
        "SELECT 1 FROM ontology_templates WHERE name = %s LIMIT 1", (name,)
    ).fetchone()
    if existing:
        raise ValueError(f"template {name!r} already exists")
    cur = conn.execute(
        f"""
        INSERT INTO ontology_templates (name, version, schema, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING {_TEMPLATE_COLS}
        """,
        (name, 1, json.dumps(schema), created_by),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def update_template(conn: Any, *, name: str, schema: dict, created_by: str) -> dict:
    """Append a new version (``max(version) + 1``); never rewrite a row.

    An as-yet unseen name gets version 1 (the literal ``max + 1`` with ``max``
    treated as 0); callers that require an existing template should guard with
    :func:`get_template` first.
    """
    if not name:
        raise ValueError("name is required")
    problems = validate_template_schema(schema)
    if problems:
        raise ValueError("; ".join(problems))
    current_max = _scalar(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version "
            "FROM ontology_templates WHERE name = %s",
            (name,),
        ).fetchone()
    )
    new_version = int(current_max or 0) + 1
    cur = conn.execute(
        f"""
        INSERT INTO ontology_templates (name, version, schema, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING {_TEMPLATE_COLS}
        """,
        (name, new_version, json.dumps(schema), created_by),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def get_template(
    conn: Any, *, name: str, version: Optional[int] = None
) -> Optional[dict]:
    """Fetch one version of a template; ``version is None`` means the latest."""
    if version is not None:
        cur = conn.execute(
            f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
            "WHERE name = %s AND version = %s",
            (name, version),
        )
    else:
        cur = conn.execute(
            f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
            "WHERE name = %s ORDER BY version DESC LIMIT 1",
            (name,),
        )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_template_by_id(conn: Any, *, template_id: int) -> Optional[dict]:
    """Fetch the exact template row a domain was anchored to."""
    cur = conn.execute(
        f"SELECT {_TEMPLATE_COLS} FROM ontology_templates WHERE id = %s",
        (template_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_templates(conn: Any) -> list[dict]:
    """One row per name: the latest version, ordered by name."""
    cur = conn.execute(
        f"""
        SELECT DISTINCT ON (name) {_TEMPLATE_COLS}
        FROM ontology_templates
        ORDER BY name, version DESC
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def list_template_versions(conn: Any, *, name: str) -> list[dict]:
    """All versions of one name, ascending."""
    cur = conn.execute(
        f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
        "WHERE name = %s ORDER BY version ASC",
        (name,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]
