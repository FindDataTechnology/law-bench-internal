"""Controlled-vocabulary tag dimensions for clauses, per contract type.

Universal dims (source/region/stance/strength/risk/mandatory) are shared across
all contract types (``contract_type=NULL`` in ``tag_dims``). Type-specific dims
belong to one contract type (``contract_type=<key>``), decoupled per type.
:func:`validate_tags` accepts universal + the given type's dims; free-form dims
(``region``) accept any non-empty string. Tags are curatorial, NOT derived from
the clause body.

The vocabulary is loaded from the ``tag_dims`` table at app startup via
:func:`load_vocab_from_db`, building ``TAG_VOCAB[contract_type][dim] = values``.
``register_tag_dim`` is the in-memory reuse-or-create governance gate (merge
values if the dim exists, else create) -- the seeder, extraction, and manual
entry all route through it so dims don't proliferate.
"""

from __future__ import annotations

TAG_CATEGORIES = ("来源", "利益倾向", "风险合规", "地域", "类型专属")

# TAG_VOCAB[contract_type][dim] = [allowed values].
# contract_type=None => universal (shared by all types).
# contract_type=<key> => type-specific (decoupled per type).
TAG_VOCAB: dict[str | None, dict[str, list[str]]] = {
    None: {
        "source": ["base", "tagged", "custom"],
        "stance": ["pro_a", "pro_b", "balanced"],
        "strength": ["strong", "standard", "mild"],
        "risk": ["high", "medium", "low"],
        "mandatory": ["mandatory", "default", "recommended"],
    }
}

# Dims that accept any non-empty string (not a controlled vocabulary).
# Populated from tag_dims.free_form at load; "region" is the starter.
FREE_FORM_TAGS: set[str] = {"region"}


def register_tag_dim(
    contract_type: str | None,
    name: str,
    category: str = "类型专属",
    values: list[str] | None = None,
    free_form: bool = False,
    zh_label: str | None = None,
) -> None:
    """Register a tag dim in-memory (reuse-or-create governance).

    If ``(contract_type, name)`` already exists in ``TAG_VOCAB``, merge values
    (don't duplicate). Otherwise create. ``free_form`` dims are added to
    ``FREE_FORM_TAGS``.
    """
    vals = [str(v) for v in (values or [])]
    bucket = TAG_VOCAB.setdefault(contract_type, {})
    if name in bucket:
        merged = list(bucket[name])
        for v in vals:
            if v not in merged:
                merged.append(v)
        bucket[name] = merged
    else:
        bucket[name] = vals
    if free_form:
        FREE_FORM_TAGS.add(name)


def load_vocab_from_db(db=None) -> dict:
    """Load tag_dims into ``TAG_VOCAB`` (per-type) + ``FREE_FORM_TAGS``.

    Best-effort: if the DB/table is unreachable, the starter set remains.
    """
    from src.eval.db import connect

    try:
        conn = connect(db)
        try:
            rows = conn.execute(
                "SELECT name, contract_type, values, free_form FROM tag_dims"
            ).fetchall()
        finally:
            if db is None:
                conn.close()
    except Exception:  # noqa: BLE001
        return TAG_VOCAB
    for r in rows:
        ct = r["contract_type"]  # None for universal
        name = r["name"]
        vals = [str(v) for v in (r["values"] or [])]
        TAG_VOCAB.setdefault(ct, {})[name] = vals
        if r["free_form"]:
            FREE_FORM_TAGS.add(name)
    return TAG_VOCAB


def validate_tags(tags: dict | None, contract_type: str | None = None) -> dict:
    """Return a clean tag dict: unknown keys dropped; bad values raise.

    Checks universal dims (``TAG_VOCAB[None]``) + type-specific dims
    (``TAG_VOCAB[contract_type]``). Free-form dims accept any non-empty string.

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
    universal = TAG_VOCAB.get(None, {})
    type_specific = TAG_VOCAB.get(contract_type, {}) if contract_type else {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        vs = str(v)
        if not vs:
            continue
        if k in FREE_FORM_TAGS:
            out[k] = vs
        elif k in universal:
            if vs not in universal[k]:
                raise ValueError(
                    f"invalid tag value: {k}={v!r}; allowed: {universal[k]}"
                )
            out[k] = vs
        elif k in type_specific:
            if vs not in type_specific[k]:
                raise ValueError(
                    f"invalid tag value: {k}={v!r}; allowed: {type_specific[k]}"
                )
            out[k] = vs
        # else: drop unknown (not in universal or this type's vocab)
    return out


def normalize_tags(tags: dict | None, contract_type: str | None = None) -> dict:
    """Safe read: validated tags, dropping unknown keys/values without raising."""
    if not tags:
        return {}
    universal = TAG_VOCAB.get(None, {})
    type_specific = TAG_VOCAB.get(contract_type, {}) if contract_type else {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        vs = str(v)
        if not vs:
            continue
        if k in FREE_FORM_TAGS:
            out[k] = vs
        elif k in universal and vs in universal[k]:
            out[k] = vs
        elif k in type_specific and vs in type_specific[k]:
            out[k] = vs
    return out


def tag_vocab_for_type(contract_type: str | None = None) -> dict[str, list[str]]:
    """Merged flat vocab for a contract type: universal + type-specific.

    Returns ``{dim: [allowed values]}`` for all dims valid for this type.
    Free-form dims (e.g. ``region``) have an empty list.
    """
    merged: dict[str, list[str]] = {}
    merged.update(TAG_VOCAB.get(None, {}))
    if contract_type:
        merged.update(TAG_VOCAB.get(contract_type, {}))
    return merged
