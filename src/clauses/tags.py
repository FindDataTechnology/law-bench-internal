"""Controlled-vocabulary tag dimensions for clauses.

A minimal universal starter set (``stance``/``strength``/``risk``/``mandatory``)
is hardcoded as the always-available baseline. Type-specific dimensions live in
the ``tag_dims`` table (populated by :func:`src.clauses.seed_manifest.seed_tag_dims`)
and are merged into the in-memory :data:`TAG_VOCAB` by :func:`load_vocab_from_db`,
which the web app calls at startup. The image therefore need not ship the seed
files - the vocabulary is read from the database, not from disk.

:func:`validate_tags` enforces the current vocabulary: unknown keys are dropped,
and an unknown value for a known key raises :class:`ValueError`. Tags are
curatorial judgments, NOT derived from the clause body (unlike
``slot_instructions`` and ``law_refs``).
"""

from __future__ import annotations

# dimension -> allowed values (strings only; YAML booleans are normalized away).
# The starter set is always present; type-specific dims are merged in from the
# tag_dims table by load_vocab_from_db (at app startup / in the seed loader).
TAG_VOCAB: dict[str, list[str]] = {
    "stance": ["pro_a", "pro_b", "balanced"],
    "strength": ["strong", "standard", "mild"],
    "risk": ["high", "medium", "low"],
    "mandatory": ["mandatory", "default", "recommended"],
}

# Tag dims that accept any non-empty string (NOT a controlled vocabulary).
# `region` (province/地域) is free-form because province names are an open set
# (and the extractor infers short names like 吉林/京/京津冀 that we don't want to
# reject). They are still tags - just not value-validated against TAG_VOCAB.
FREE_FORM_TAGS: set[str] = {"region"}


def register_tag_dim(name: str, values: list[str]) -> None:
    """Register a tag dimension, or extend it if it already exists.

    This mutates the in-memory :data:`TAG_VOCAB` only; to persist a new
    dimension, add it to a seed manifest and re-run ``seed_tag_dims``. Values
    are coerced to ``str`` (YAML parses unquoted ``yes``/``no`` as booleans).
    """
    vals = [str(v) for v in values]
    if name in TAG_VOCAB:
        merged = list(TAG_VOCAB[name])
        for v in vals:
            if v not in merged:
                merged.append(v)
        TAG_VOCAB[name] = merged
    else:
        TAG_VOCAB[name] = vals


def load_vocab_from_db(db=None) -> dict:
    """Merge tag dimensions from the ``tag_dims`` table into :data:`TAG_VOCAB`.

    Idempotent: starter 4 + every row in ``tag_dims``. Called at app startup so
    the image need not read seed files at runtime. Best-effort: if the DB or the
    table is unreachable, the starter set remains and the app still starts.
    """
    from src.eval.db import connect

    try:
        conn = connect(db)
        try:
            rows = conn.execute("SELECT name, values FROM tag_dims").fetchall()
        finally:
            if db is None:
                conn.close()
    except Exception:  # noqa: BLE001 - DB/table missing -> starter 4 only
        return TAG_VOCAB
    for r in rows:
        name = r["name"]
        vals = r["values"]
        if name and isinstance(vals, list):
            register_tag_dim(name, [str(v) for v in vals])
    return TAG_VOCAB


def validate_tags(tags: dict | None) -> dict:
    """Return a clean tag dict: unknown keys dropped; bad values raise.

    Free-form dims (``FREE_FORM_TAGS``, e.g. ``region``) accept any non-empty
    string. Controlled dims (``TAG_VOCAB``) reject out-of-vocabulary values.

    >>> validate_tags({"stance": "pro_a", "mood": "happy"})
    {'stance': 'pro_a'}
    >>> validate_tags({"region": "吉林"})
    {'region': '吉林'}
    >>> validate_tags({"stance": "pro_A"})
    Traceback (most recent call last):
        ...
    ValueError: invalid tag value: stance='pro_A'; allowed: ['pro_a', 'pro_b', 'balanced']
    """
    if not tags:
        return {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        vs = str(v)
        if not vs:
            continue  # drop empty values
        if k in FREE_FORM_TAGS:
            out[k] = vs
        elif k in TAG_VOCAB:
            if vs not in TAG_VOCAB[k]:
                raise ValueError(
                    f"invalid tag value: {k}={v!r}; allowed: {TAG_VOCAB[k]}"
                )
            out[k] = vs
        # else: drop unknown keys
    return out


def normalize_tags(tags: dict | None) -> dict:
    """Safe read: validated tags, dropping unknown keys/values without raising."""
    if not tags:
        return {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        vs = str(v)
        if not vs:
            continue
        if k in FREE_FORM_TAGS:
            out[k] = vs
        elif k in TAG_VOCAB and vs in TAG_VOCAB[k]:
            out[k] = vs
    return out
