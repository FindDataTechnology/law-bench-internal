"""Import contract-generator rules into law-bench via the generator's own loader.

Reuses :class:`contract_rules.loader.RulesRegistry` (chain / elements_for /
clauses_for / validations_for) — the loader already implements inheritance,
dedup, and field-level merge, so we never re-parse the YAMLs ad hoc.

Tasks 5/6/7 additions:
- Sub-type leaf → tagged mapping (``SUBTYPE_SCENARIOS`` + :func:`import_subtypes`)
- Idempotency + drift (``tag_review`` stamps + :func:`drift_report`)
- slot_instructions enrichment (``prompt``/``type``/``enum_values``)
"""

from __future__ import annotations

import hashlib
import re  # noqa: F401  (kept for downstream consumers that `from generator_import import re`)
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# generator package lives outside law-bench's src tree; put its parent on sys.path
# parents[0]=clauses  parents[1]=src  parents[2]=law-template
_GENERATOR_ROOT = Path(__file__).resolve().parents[2] / "contract-generator" / "合同生成规则"
if str(_GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_GENERATOR_ROOT))

from contract_rules.loader import RulesRegistry, _build_registry  # noqa: E402

RULES_DIR = _GENERATOR_ROOT / "contract_rules" / "rules"


def _source_hash() -> str:
    """MD5 over all elements/clauses/validation YAMLs — drift fingerprint."""
    h = hashlib.md5()
    for sub in ("elements", "clauses", "validation"):
        d = RULES_DIR / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.yaml")):
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def build_registry() -> tuple[RulesRegistry, str]:
    """Instantiate the generator's RulesRegistry (sync) + rules-dir source hash."""
    return _build_registry(), _source_hash()


# generator clause title → law-bench SECTION_ORDER bucket (best-effort)
_TITLE_KEYWORDS = (
    ("当事人", "当事人"), ("标的", "合同标的"), ("金额", "价款及支付"),
    ("价款", "价款及支付"), ("付款", "价款及支付"), ("费用", "价款及支付"),
    ("期限", "履行期限"), ("交付", "履行期限"), ("履行", "履行期限"),
    ("权利", "权利义务"), ("义务", "权利义务"), ("违约", "违约责任"),
    ("争议", "争议解决"), ("通知", "争议解决"), ("附则", "附则"), ("签署", "签署信息"),
)


def section_from_title(title: str) -> str:
    t = (title or "").strip()
    for kw, sec in _TITLE_KEYWORDS:
        if kw in t:
            return sec
    return t or "附则"


# ── Task 5: sub-type leaf → tagged scenario mapping ──────────────────────
# Transcribed from design.md Category A table. Only leaves that become
# *tagged* clauses under their parent law-bench type are listed here.
# Leaves that map 1:1 to a *different* law-bench type as base (e.g.
# lease.immovable.house→real_estate_lease, lease.financing→financing_lease,
# technology.development→software_development, technology.license→ip_license,
# sale.movable→sale base, sale.real-estate→real_estate_sale base,
# loan.civil→loan base, transport.freight→transport base,
# project.construction→construction base, work.processing→work base,
# labor→employment) are deliberately NOT in this dict — they're handled by
# import_type (base), not import_subtypes (tagged).
SUBTYPE_SCENARIOS: dict[str, tuple[str, str]] = {
    # sale → sale tagged
    "sale.vehicle":                 ("sale",         "车辆买卖"),
    # lease → lease tagged
    "lease.immovable.shop":         ("lease",        "商铺租赁"),
    "lease.immovable.office":       ("lease",        "办公楼租赁"),
    "lease.immovable.warehouse":    ("lease",        "厂房仓库租赁"),
    "lease.immovable.parking":      ("lease",        "车位租赁"),
    "lease.movable.vehicle":        ("lease",        "车辆租赁"),
    "lease.equipment.computer":     ("lease",        "电脑租赁"),
    "lease.equipment.printer":      ("lease",        "打印机租赁"),
    "lease.equipment.construction": ("lease",        "建筑设备租赁"),
    "lease.equipment.phone":        ("lease",        "手机租赁"),
    # loan → loan tagged (civil→base)
    "loan.financial":               ("loan",         "金融借款"),
    # transport → transport tagged (freight→base)
    "transport.passenger":          ("transport",    "旅客运输"),
    "transport.multimodal":         ("transport",    "多式联运"),
    # technology → technology tagged (development→software_development, license→ip_license)
    "technology.transfer":          ("technology",   "技术转让"),
    "technology.consulting":        ("technology",   "技术咨询/服务"),
    # project → construction tagged (construction→base)
    "project.survey":               ("construction", "工程勘察"),
    "project.design":               ("construction", "工程设计"),
    # work → work tagged (processing→base)
    "work.custom":                  ("work",         "定作"),
    "work.repair":                  ("work",         "修理"),
    "work.decoration":              ("work",         "装饰装修"),
}


# ── Task 7: slot_instructions enrichment ──────────────────────────────────

def _parse_element_type(raw: str | None) -> tuple[str, list[str] | None]:
    """Parse a generator element ``type`` string into (base_type, enum_values).

    ``enum{A, B}`` → ``("enum", ["A", "B"])``; ``duration{months}`` →
    ``("duration", None)``; ``money`` → ``("money", None)``;
    ``list[{name, brand}]`` → ``("list", None)``.
    """
    if not raw:
        return "text", None
    base = raw.split("{", 1)[0].strip()
    if base == "enum":
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            inner = raw[start + 1:end]
            vals = [v.strip() for v in inner.split(",") if v.strip()]
            return "enum", vals
    return base, None


def _slot_instructions_for(contract_type: str, registry: RulesRegistry) -> list[dict]:
    """Build slot_instructions from generator elements (enriched 8-key form).

    Element ``id`` is the ``{{slot}}`` name used in clause bodies, so every body
    slot is covered and the coherence gate passes. Enriched with ``prompt``
    (大白话问法), ``type`` (money|enum|date|duration|text|number|list), and
    ``enum_values`` (only when type==enum). Field-level inheritance (loan
    redefining 甲方名称→甲方(出借人)名称 while inheriting required/type) is
    already resolved by the loader's ``elements_for()`` field-merge —
    ``e.get("name")`` is the per-type label, so NO extra per-type override
    code is needed.
    """
    out: list[dict] = []
    for e in registry.elements_for(contract_type):
        base_type, enum_vals = _parse_element_type(e.get("type"))
        entry: dict[str, Any] = {
            "name": e.get("id"),
            "label": e.get("name") or e.get("id"),
            "description": e.get("prompt") or "",
            "example": "",
            "required": bool(e.get("required", False)),
        }
        prompt = e.get("prompt")
        if prompt:
            entry["prompt"] = prompt
        if base_type:
            entry["type"] = base_type
        if base_type == "enum" and enum_vals:
            entry["enum_values"] = enum_vals
        out.append(entry)
    return out


# ── Task 6: idempotency + drift ────────────────────────────────────────────

def clause_records(
    contract_type: str,
    registry: RulesRegistry | None = None,
    source_hash: str | None = None,
) -> list[dict]:
    """Build law-bench clause dicts (ready for ``upsert_clause``) from generator rules.

    ``source_path`` is keyed ``generator://<type>/<clause_id>`` so re-runs hit the
    upsert conflict clause (idempotent). ``tag_review`` stamps
    ``_source_hash`` (the ``build_registry()`` hash) and ``_imported_at`` (ISO
    timestamp) for drift detection — stored in the free-form jsonb field, NOT
    passed through ``validate_tags``, so no tags.py or DDL change is needed.
    ``upsert_clause``'s ON CONFLICT DO UPDATE does not refresh ``tag_review``,
    but that's fine: a changed YAML changes the body → new ``body_hash`` → new
    row (no conflict) → fresh hash; unchanged YAML → same hash → no false drift.
    """
    if registry is None:
        registry, source_hash = build_registry()
    elif source_hash is None:
        source_hash = _source_hash()
    now_iso = datetime.now().isoformat()
    instructions = _slot_instructions_for(contract_type, registry)
    out: list[dict] = []
    for c in registry.clauses_for(contract_type):
        body = (c.get("text") or "").strip()
        if not body:
            continue
        out.append({
            "contract_type": contract_type,
            "section": section_from_title(c.get("title")),
            "body": body,
            "slot_instructions": instructions,
            "source_path": f"generator://{contract_type}/{c.get('id')}",
            "source_doc_title": c.get("source") or "",
            "tags": {"source": "base"},
            "category": "base",
            "tag_review": {"_source_hash": source_hash, "_imported_at": now_iso},
        })
    return out


def import_type(
    contract_type: str,
    db: Any = None,
    dry_run: bool = True,
    registry: RulesRegistry | None = None,
) -> dict:
    """Upsert generator clauses for one type; return ``{written, skipped, ids}``.

    ``dry_run=True`` (default) prints actions without writing — safe smoke test.
    """
    records = clause_records(contract_type, registry)
    if dry_run:
        for r in records:
            print(f"[DRY] {contract_type}/{r['section']}: {r['body'][:50]}…")
        return {"written": 0, "skipped": len(records), "ids": []}

    from src.clauses.store import upsert_clause
    ids: list[int] = []
    for r in records:
        ids.append(upsert_clause(r, db))
    return {"written": len(ids), "skipped": 0, "ids": ids}


# ── Task 5: sub-type leaf → tagged import ──────────────────────────────────

def _leaf_clause_records(
    leaf_id: str,
    contract_type: str,
    scenario: str,
    registry: RulesRegistry,
    source_hash: str,
) -> list[dict]:
    """Build tagged clause dicts for one sub-type leaf's own clauses.

    Only the leaf's own clauses (``registry._clauses[leaf_id]``) are emitted as
    tagged; the parent chain's clauses are already imported as base by
    :func:`import_type`. Slot instructions come from the leaf's full-chain
    elements (``elements_for(leaf_id)``) so all body slots are covered.
    """
    instructions = _slot_instructions_for(leaf_id, registry)
    now_iso = datetime.now().isoformat()
    out: list[dict] = []
    for c in registry._clauses.get(leaf_id, []):
        body = (c.get("text") or "").strip()
        if not body:
            continue
        out.append({
            "contract_type": contract_type,
            "section": section_from_title(c.get("title")),
            "body": body,
            "slot_instructions": instructions,
            "source_path": f"generator://{leaf_id}/{c.get('id')}",
            "source_doc_title": c.get("source") or "",
            "tags": {"source": "tagged", "scenario": scenario},
            "category": "tagged",
            "tag_review": {"_source_hash": source_hash, "_imported_at": now_iso},
        })
    return out


def import_subtypes(
    contract_type: str,
    db: Any = None,
    dry_run: bool = True,
    registry: RulesRegistry | None = None,
) -> dict:
    """Upsert tagged clauses for sub-type leaves belonging to ``contract_type``.

    For each leaf in :data:`SUBTYPE_SCENARIOS` whose mapped law-bench type ==
    ``contract_type``, the leaf's own clauses are stored as ``tagged`` with a
    ``scenario`` tag. The parent type's base clauses are handled by
    :func:`import_type`. The existing ``list_clauses`` scenario filter
    (``tags->>'scenario'``) picks these up at assembly — no assemble.py edit
    needed. Returns ``{written, skipped, leaves, ids}``.
    """
    if registry is None:
        registry, source_hash = build_registry()
    else:
        source_hash = _source_hash()
    leaves = [
        (leaf, ct, sc) for leaf, (ct, sc) in SUBTYPE_SCENARIOS.items()
        if ct == contract_type
    ]
    records: list[dict] = []
    for leaf_id, _ct, scenario in leaves:
        records.extend(
            _leaf_clause_records(leaf_id, contract_type, scenario, registry, source_hash)
        )
    if dry_run:
        for r in records:
            print(f"[DRY] {r['source_path']}: {r['body'][:50]}…")
        return {"written": 0, "skipped": len(records), "leaves": len(leaves), "ids": []}

    from src.clauses.store import upsert_clause
    ids: list[int] = []
    for r in records:
        ids.append(upsert_clause(r, db))
    return {"written": len(ids), "skipped": 0, "leaves": len(leaves), "ids": ids}


def drift_report(db: Any = None) -> list[dict]:
    """Return types whose stored ``_source_hash`` differs from the current registry.

    Reads ``tag_review->>'_source_hash'`` from the ``clauses`` table and
    compares against a fresh ``_source_hash()``. Types with no stored hash
    (pre-Task-6 rows) are ignored. Returns ``[{contract_type, stored_hash,
    current_hash, drifted: bool}]`` — entries with ``drifted=True`` need a
    re-import to refresh stale clause rows.
    """
    from src.eval.db import connect

    current = _source_hash()
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT DISTINCT contract_type, tag_review->>'_source_hash' AS stored_hash "
            "FROM clauses WHERE tag_review->>'_source_hash' IS NOT NULL"
        ).fetchall()
    finally:
        if db is None:
            conn.close()
    out: list[dict] = []
    for r in rows:
        stored = r["stored_hash"]
        out.append({
            "contract_type": r["contract_type"],
            "stored_hash": stored,
            "current_hash": current,
            "drifted": stored != current,
        })
    return out


if __name__ == "__main__":
    reg, h = build_registry()
    leaves = reg.leaf_types()
    print(f"registry OK | types={len(reg.types)} leaves={len(leaves)} | source_hash={h}")
    chain = reg.chain("loan")
    print(f"loan chain={chain}")
    print(f"loan elements={len(reg.elements_for('loan'))} "
          f"clauses={len(reg.clauses_for('loan'))} "
          f"validations={len(reg.validations_for('loan'))}")
    # field-level inheritance sanity: loan redefines 甲方名称 → 甲方（出借人）名称
    for e in reg.elements_for("loan"):
        if e.get("id") == "甲方名称":
            print(f"  甲方名称 → name='{e.get('name')}' required={e.get('required')} "
                  f"type={e.get('type')} inherited_from={e.get('inherited_from')}")
            break
    import_type("loan", dry_run=True, registry=reg)
    # Task 5: sub-type tagged import dry-run
    print(f"\nSUBTYPE_SCENARIOS: {len(SUBTYPE_SCENARIOS)} leaves mapped")
    result = import_subtypes("lease", dry_run=True, registry=reg)
    print(f"lease subtypes: {result}")
    # Task 7: enriched slot_instructions sample
    instr = _slot_instructions_for("loan", reg)
    for e in instr:
        if e.get("name") == "甲方名称":
            print(f"\n  enriched 甲方名称: label='{e.get('label')}' prompt='{e.get('prompt')}' "
                  f"type='{e.get('type')}' required={e.get('required')}")
        if e.get("name") == "还款方式":
            print(f"  enriched 还款方式: type='{e.get('type')}' "
                  f"enum_values={e.get('enum_values')}")
