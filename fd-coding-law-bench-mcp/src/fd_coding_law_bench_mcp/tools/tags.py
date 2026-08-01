"""Read-only tag-vocabulary tools.

Wrap :mod:`src.clauses.tags`: ``tag_vocab_list`` exposes the merged flat
vocabulary for a contract type (universal + type-specific dims), and
``tag_validate`` dry-runs a tag dict against the controlled vocabulary. Both
refresh the in-memory ``TAG_VOCAB`` from ``tag_dims`` first (idempotent,
best-effort) so type-specific dims are reflected, mirroring
``contract_generate``'s ``include_current_tags`` path. Neither writes to the
``tag_dims`` table or registers new dimensions.
"""

from __future__ import annotations

from ..server import mcp


@mcp.tool(tags={"tags"})
def tag_vocab_list(contract_type: str | None = None) -> dict[str, list[str]]:
    """List the merged flat tag vocabulary for a contract type.

    Returns ``{dim: [allowed values]}`` for every dimension valid for the type:
    universal starter dims (``stance`` / ``strength`` / ``risk`` / ``mandatory``)
    merged with the type-specific dims from the ``tag_dims`` table. When
    ``contract_type`` is ``None``, returns only the universal dims.

    Parameters:
        contract_type: contract class key, or ``None`` for universal-only.

    Read-only: does not write to ``tag_dims`` or register new dimensions.
    """
    from src.clauses.tags import load_vocab_from_db, tag_vocab_for_type

    load_vocab_from_db()
    return tag_vocab_for_type(contract_type)


@mcp.tool(tags={"tags"})
def tag_validate(tags: dict, contract_type: str | None = None) -> dict:
    """Validate a tag dict against the controlled vocabulary.

    Returns the cleaned dict: unknown keys are dropped, and ``scenario`` plus
    free-form dims are kept (any non-empty value). For a controlled dim with an
    invalid value, raises a tool error naming the dim, the bad value, and the
    allowed set.

    Parameters:
        tags: tag dict to validate.
        contract_type: contract class key (selects type-specific controlled
            dims); ``None`` validates against universal dims only.

    Read-only: does not write to ``tag_dims`` or register new dimensions.
    """
    from src.clauses.tags import load_vocab_from_db, validate_tags

    load_vocab_from_db()
    return validate_tags(tags, contract_type)
