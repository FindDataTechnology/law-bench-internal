"""Batch-fix base-clause pollution for the 14 remaining contract types.

Same fix as sale (see /tmp/retag_sale_base.py & sale-base-pollution-fix memory):
each type's base was bulk-loaded from multiple 示范文本 -> variant piling. Here we
  Phase 2 (first): seed clean 母版 base from contracts.json (source_doc_title
           = '生成母版（{zh}）', manual=true, tags.source=base), section-normalized.
  Phase 1: re-tag the old 示范文本 base -> tags.source=tagged + tags.scenario.

Per-type commit (resumable). Rollback: output/_retag_rollback_batch.json.
Also aligns sale's prior 母版 seeds to the '生成母版（{zh}）' marker for consistency.
"""
from __future__ import annotations
import json, re
from src.eval.db import connect
from src.clauses.store import _INSERT_COLS, _row, _finalize, ensure_schema, _now
from src.clauses.extract import SECTION_ORDER
from src.contracts.templates import list_contract_types

TYPES = [
    "utilities_supply", "lease", "work", "construction", "transport",
    "entrustment", "property_service", "brokerage", "intermediation",
    "real_estate_sale", "franchise", "tourism_service", "service", "land_transfer",
]
RB_FILE = "output/_retag_rollback_batch.json"
ZH = {t["key"]: t["zh"] for t in list_contract_types()}
CATALOG = {x["key"]: x for x in json.load(open("src/contracts/data/contracts.json"))}


def norm_section(h: str) -> str:
    h = re.sub(r"^第[一二三四五六七八九十百]+条\s*", "", h.strip())
    h = re.sub(r"[（(]?(示范文本|试行)[）)]?", "", h)
    h = h.replace("（订货）", "").replace("(订货)", "")
    h = re.sub(r"合同$", "", h)
    if h == "价款及支付方式":
        h = "价款及支付"
    if h == "双方权利义务":
        h = "权利义务"
    return h.strip().strip("（）()")


def to_scenario(title: str) -> str:
    s = re.sub(r"[（(]?(示范文本|试行)[）)]?", "", title)
    s = s.replace("（订货）", "").replace("(订货)", "")
    s = re.sub(r"合同$", "", s)
    s = s.strip().strip("（）()")
    return s or title


def seed_mother(conn, k: str) -> list[int]:
    zh = ZH[k]
    marker = f"生成母版（{zh}）"
    conn.execute("DELETE FROM clauses WHERE contract_type=%s AND source_doc_title=%s", (k, marker))
    sale = CATALOG[k]
    mother_si = sale.get("slot_instructions") or []
    ids = []
    for p in re.split(r"^## ", sale["body"], flags=re.M):
        if not p.strip():
            continue
        head, _, rest = p.partition("\n")
        sec = norm_section(head)
        if sec not in SECTION_ORDER:
            print(f"    [skip] {k}: unknown section {head!r} -> {sec!r}")
            continue
        body = rest.strip()
        rec = _finalize({
            "contract_type": k, "section": sec, "body": body,
            "slot_instructions": mother_si, "law_refs": [],
            "source_path": None, "source_doc_title": marker,
            "manual": True, "tags": {"source": "base"}, "tag_review": {},
        }, body)
        cur = conn.execute(
            "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            _row(rec, now=_now()),
        )
        ids.append(cur.fetchone()["id"])
    return ids


def retag_old_base(conn, k: str) -> int:
    zh = ZH[k]
    marker = f"生成母版（{zh}）"
    rows = conn.execute(
        "SELECT id, source_doc_title, tags FROM clauses "
        "WHERE contract_type=%s AND tags->>'source'='base' AND source_doc_title <> %s",
        (k, marker),
    ).fetchall()
    total = 0
    for r in rows:
        scen = to_scenario(r["source_doc_title"] or "")
        conn.execute(
            "UPDATE clauses SET "
            "  tags = jsonb_set(jsonb_set(tags, '{source}', '\"tagged\"', true), "
            "                        '{scenario}', to_jsonb(%s::text), true), "
            "  updated_at = %s WHERE id = %s",
            (scen, _now(), r["id"]),
        )
        total += 1
    return total


def main() -> None:
    conn = connect()
    ensure_schema(conn)
    rollback = {}
    try:
        for k in TYPES:
            zh = ZH[k]
            # snapshot old base (non-母版) for rollback
            rows = conn.execute(
                "SELECT id, source_doc_title, tags FROM clauses "
                "WHERE contract_type=%s AND tags->>'source'='base' AND source_doc_title NOT LIKE '生成母版%%'",
                (k,),
            ).fetchall()
            rollback[k] = [{"id": r["id"], "source_doc_title": r["source_doc_title"], "tags": r["tags"]} for r in rows]

            seeded = seed_mother(conn, k)
            nretag = retag_old_base(conn, k)
            conn.commit()

            base_n = conn.execute("SELECT COUNT(*) n FROM clauses WHERE contract_type=%s AND tags->>'source'='base'", (k,)).fetchone()["n"]
            print(f"[{k:22s}] seeded={len(seeded):2d}  retag={nretag:3d}  base_now={base_n}")
        json.dump(rollback, open(RB_FILE, "w"), ensure_ascii=False, indent=1)
        print(f"\n[rollback] {sum(len(v) for v in rollback.values())} clauses -> {RB_FILE}")

        # align sale's prior 母版 seeds to '生成母版（买卖合同）' for consistency
        conn.execute("UPDATE clauses SET source_doc_title='生成母版（买卖合同）' WHERE contract_type='sale' AND source_doc_title='母版·买卖合同(contracts.json)'")
        conn.commit()
        print("[align] sale 母版 seeds -> '生成母版（买卖合同）'")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
