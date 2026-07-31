"""``generate_contract_from_tags`` tool.

Wraps :func:`src.contracts.generate_contract` (skeleton 母版 template) and
:func:`src.clauses.assemble.generate_contract_assembled` (base + tagged + custom
clause assembly). When ``include_current_tags`` is set, attaches the live
custom-tag vocabulary (starter + ``tag_dims`` + any runtime-registered dims).
"""

from __future__ import annotations

from ..server import mcp


@mcp.tool
def generate_contract_from_tags(
    contract_type: str,
    format: str = "pdf",
    tags: dict | None = None,
    stance: str | None = None,
    out_dir: str | None = None,
    include_current_tags: bool = False,
) -> dict:
    """Generate a contract deliverable (DOCX/PDF) for a contract class.

    By default renders the registered 母版 template (skeleton). When ``stance``
    and/or a ``tags`` dict carrying ``stance`` / ``region`` is supplied, assembles
    base + provincial-tagged + custom clauses and filters the custom-clause
    selection by the given stance (``pro_a`` / ``pro_b`` / ``balanced``) and the
    tagged selection by region/province.

    Parameters:
        contract_type: contract class key, e.g. ``"sale"`` or ``"employment"``.
        format: ``"docx"`` / ``"pdf"`` / ``"both"`` (default ``"pdf"``).
        tags: optional dict; recognized keys are ``stance`` and ``region``
            (or ``province``). Other keys are ignored.
        stance: convenience for ``tags["stance"]``.
        out_dir: output directory (default ``output/contracts``).
        include_current_tags: when True, attach ``current_tags`` - the live
            custom-tag vocabulary (starter set + ``tag_dims`` rows + any dims
            registered in-process via ``register_tag_dim``), so the caller can
            see which tag values are currently available.

    Returns ``{docx_path, pdf_path, slots, instructions, ...}`` where the
    skeleton path also includes ``laws`` and the assembled path includes
    ``law_refs``; plus ``current_tags`` when requested. An unknown
    ``contract_type`` raises a tool error.
    """
    from src.clauses.assemble import generate_contract_assembled
    from src.contracts import generate_contract

    # Derive the effective stance + province (region). The underlying assembler
    # only filters custom clauses by `stance` and tagged clauses by `province`,
    # so we surface exactly those two dimensions from `tags`.
    if tags:
        stance = stance or tags.get("stance")
        province = tags.get("region") or tags.get("province")
    else:
        province = None

    if stance or province:
        result = generate_contract_assembled(
            contract_type,
            province=province,
            stance=stance,
            format=format,
            out_dir=out_dir,
        )
    else:
        result = generate_contract(contract_type, format=format, out_dir=out_dir)

    if include_current_tags:
        from src.clauses.tags import TAG_VOCAB, load_vocab_from_db

        # Merge tag_dims into the live TAG_VOCAB (idempotent, best-effort:
        # degrades to the starter set if the DB is unreachable). A shallow copy
        # so the caller cannot mutate the server's process vocabulary.
        load_vocab_from_db()
        result["current_tags"] = dict(TAG_VOCAB)

    return result
