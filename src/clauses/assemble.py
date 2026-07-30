"""Assemble a contract from base + provincial-tagged + custom clauses.

:func:`generate_contract_assembled` selects clauses from the ``clauses`` table
(base for the type, tagged for the type + province, custom by id), orders them
by the canonical section order, stitches their bodies into one Markdown body,
and renders it to DOCX/PDF via ``src/docs`` with every ``{{slot}}`` left as a
highlighted, fillable placeholder. The returned ``instructions`` is the union of
the 12 canonical slot instructions plus any clause-declared slots; ``law_refs``
is the deduped union. The existing skeleton ``generate_contract`` is unchanged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from src.contracts.slots import REQUIRED_SLOTS, default_slot_instructions
from src.contracts.templates import list_contract_types
from src.docs import SLOT_PATTERN, ConverterNotAvailableError, create_docx, docx_to_pdf
from src.eval.errors import NotFoundError
from src.eval.legal_refs import CATEGORY_ORDER

from .extract import SECTION_ORDER, section_rank
from .store import get_custom_clause, list_clauses

_FORMATS = ("docx", "pdf", "both")
# src/clauses/assemble.py -> src/clauses -> src -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATEGORY_RANK = {"base": 0, "tagged": 1, "custom": 2}


def _zh_name(contract_type: str) -> str:
    for t in list_contract_types():
        if t["key"] == contract_type:
            return t["zh"]
    return contract_type


def _select_clauses(
    contract_type: str,
    province: str | None,
    custom_clause_ids: list[int] | None,
    stance: str | None = None,
    db: Any = None,
) -> list[dict]:
    clauses = list_clauses(contract_type, category="base", db=db)
    if province:
        clauses += list_clauses(contract_type, category="tagged", province=province, db=db)
    if custom_clause_ids:
        for cid in custom_clause_ids:
            c = get_custom_clause(cid, db=db)
            if c is not None and (stance is None or (c.get("tags") or {}).get("stance") == stance):
                clauses.append(c)
    elif stance:
        clauses += list_clauses(
            contract_type, category="custom", tags={"stance": stance}, db=db
        )
    return clauses


def _assemble_body(clauses: list[dict]) -> str:
    """Stitch clause bodies into one Markdown body, grouped by section.

    Clauses are ordered by (section_rank, category rank, id); within a section
    bodies are joined, and the section heading is emitted once. Duplicate bodies
    (same ``body_hash``) within a section are collapsed.
    """
    clauses.sort(key=lambda c: (section_rank(c["section"]), _CATEGORY_RANK.get(c["category"], 9), c["id"]))
    sections: list[tuple[str, list[dict]]] = []
    index: dict[str, int] = {}
    for c in clauses:
        if c["section"] not in index:
            index[c["section"]] = len(sections)
            sections.append((c["section"], []))
        sections[index[c["section"]]][1].append(c)
    parts: list[str] = []
    for section, group in sections:
        seen: set[str] = set()
        bodies: list[str] = []
        for c in group:
            if c["body_hash"] in seen:
                continue
            seen.add(c["body_hash"])
            bodies.append(c["body"].strip())
        if not bodies:
            continue
        parts.append(f"## {section}\n\n" + "\n\n".join(bodies))
    return "\n\n".join(parts).strip()


def _build_instructions(clauses: list[dict], zh: str) -> list[dict]:
    """12 canonical slot instructions ∪ clause-declared slots (deduped by name)."""
    instructions: list[dict] = []
    names: set[str] = set()
    for ins in default_slot_instructions(zh):
        if ins["name"] not in names:
            names.add(ins["name"])
            instructions.append(dict(ins))
    for c in clauses:
        for ins in c.get("slot_instructions") or []:
            if ins.get("name") and ins["name"] not in names:
                names.add(ins["name"])
                instructions.append(
                    {
                        "name": ins["name"],
                        "label": ins.get("label") or ins["name"],
                        "description": ins.get("description") or "",
                        "example": ins.get("example") or "",
                        "required": bool(ins.get("required", False)),
                    }
                )
    return instructions


def _build_law_refs(clauses: list[dict]) -> list[dict]:
    """Deduped union of clause law_refs, sorted by (category order, name)."""
    by_name: dict[str, dict] = {}
    for c in clauses:
        for r in c.get("law_refs") or []:
            name = r.get("name")
            if not name or name in by_name:
                continue
            by_name[name] = {
                "name": name,
                "category": r.get("category", "other"),
                "category_zh": r.get("category_zh", "其他"),
            }
    out = list(by_name.values())

    def _key(r):
        cat = r["category"]
        return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER), r["name"])

    out.sort(key=_key)
    return out


def generate_contract_assembled(
    contract_type: str,
    *,
    province: str | None = None,
    custom_clause_ids: list[int] | None = None,
    stance: str | None = None,
    format: str = "pdf",
    out_dir: str | Path | None = None,
    db: Any = None,
) -> dict:
    """Assemble and render a contract from base + tagged + custom clauses.

    ``format`` is ``"docx"``, ``"pdf"``, or ``"both"``. Files are written under
    ``out_dir`` (default ``output/contracts``). Every ``{{slot}}`` is rendered as
    a highlighted, fillable placeholder (no slot is pre-filled). Returns
    ``{docx_path, pdf_path, slots, instructions, law_refs}`` where unrequested
    formats map to ``None``. Raises :class:`NotFoundError` for an unknown contract
    type (not in the 41-type catalog). ``db`` is an optional borrowed connection
    (request/test scope); left None, the store opens its own.
    """
    if format not in _FORMATS:
        raise ValueError(f"unsupported format: {format!r}; use one of {_FORMATS}")
    valid_keys = {t["key"] for t in list_contract_types()}
    if contract_type not in valid_keys:
        raise NotFoundError(f"unknown contract type: {contract_type!r}")

    zh = _zh_name(contract_type)
    clauses = _select_clauses(contract_type, province, custom_clause_ids, stance, db=db)
    body = _assemble_body(clauses)
    instructions = _build_instructions(clauses, zh)
    law_refs = _build_law_refs(clauses)
    slots = list(dict.fromkeys(SLOT_PATTERN.findall(body)))

    out = Path(out_dir) if out_dir else _REPO_ROOT / "output" / "contracts"
    out.mkdir(parents=True, exist_ok=True)

    docx_path: Path | None = None
    pdf_path: Path | None = None
    base_name = contract_type if not province else f"{contract_type}__{province}"
    if format == "docx":
        docx_path = out / f"{base_name}.docx"
        create_docx(body, str(docx_path), title=zh)
    elif format == "both":
        docx_path = out / f"{base_name}.docx"
        pdf_path = out / f"{base_name}.pdf"
        create_docx(body, str(docx_path), title=zh)
        docx_to_pdf(str(docx_path), output_path=str(pdf_path))
    else:  # pdf
        pdf_path = out / f"{base_name}.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_docx = Path(tmp) / f"{base_name}.docx"
            create_docx(body, str(tmp_docx), title=zh)
            docx_to_pdf(str(tmp_docx), output_path=str(pdf_path))

    return {
        "docx_path": str(docx_path) if docx_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "slots": slots,
        "instructions": instructions,
        "law_refs": law_refs,
    }
