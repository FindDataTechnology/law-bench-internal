"""Re-tag sale's polluted base clauses and seed a clean 母版 base.

Problem: 204 `sale` base clauses came from 21 示范文本 (家具买卖/农药买卖/...).
They are mutually-exclusive scenario variants, but `_select_clauses` pulls ALL
base clauses, so every assembled sale contract becomes a 21-way Frankenstein
(21 当事人 blocks, etc.).

Fix (user-approved "重新打标"):
  Phase 2 (first, so base is never empty): seed 10 base clauses by splitting the
      canonical 母版 (contracts.json) per section. tags.source=base, manual=true.
  Phase 1: re-tag the 204 old base clauses -> tags.source=tagged + tags.scenario
      (derived from source_doc_title).

Re-runnable: deletes prior 母版 seeds first; Phase 1 is idempotent on source.
Rollback: saves old (id, tags) to output/_retag_rollback_sale.json.
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone

from src.eval.db import connect
from src.clauses.store import _INSERT_COLS, _row, _finalize, ensure_schema, _now
from src.clauses.extract import SECTION_ORDER

CONN = connect()
ensure_schema(CONN)
RB_FILE = "output/_retag_rollback_sale.json"
MOTHER_TITLE = "母版·买卖合同(contracts.json)"
SEC_MAP = {"双方权利义务": "权利义务"}  # 母版 -> canonical SECTION_ORDER


def to_scenario(title: str) -> str:
    s = title.replace("（示范文本）", "").replace("合同", "").replace("（订货）", "").strip().strip("（）")
    return s or title


def main() -> None:
    # --- rollback snapshot of current sale base ---
    rows = CONN.execute(
        "SELECT id, source_doc_title, tags FROM clauses "
        "WHERE contract_type='sale' AND tags->>'source'='base'"
    ).fetchall()
    old = [{"id": r["id"], "source_doc_title": r["source_doc_title"], "tags": r["tags"]} for r in rows]
    json.dump(old, open(RB_FILE, "w"), ensure_ascii=False, indent=1)
    docs = sorted({o["source_doc_title"] for o in old})
    print(f"[snapshot] {len(old)} sale base clauses ({len(docs)} docs) -> {RB_FILE}")

    # === Phase 2: seed 母版 base (run FIRST so base never goes empty) ===
    CONN.execute(f"DELETE FROM clauses WHERE contract_type='sale' AND source_doc_title=%s", (MOTHER_TITLE,))
    sale = [x for x in json.load(open("src/contracts/data/contracts.json")) if x["key"] == "sale"][0]
    mother_si = sale.get("slot_instructions") or []
    seeded = []
    for p in re.split(r"^## ", sale["body"], flags=re.M):
        if not p.strip():
            continue
        head, _, rest = p.partition("\n")
        sec = SEC_MAP.get(head.strip(), head.strip())
        if sec not in SECTION_ORDER:
            print(f"  [skip] unknown section: {sec!r}")
            continue
        body = rest.strip()
        rec = _finalize({
            "contract_type": "sale", "section": sec, "body": body,
            "slot_instructions": mother_si, "law_refs": [],
            "source_path": None, "source_doc_title": MOTHER_TITLE,
            "manual": True, "tags": {"source": "base"}, "tag_review": {},
        }, body)
        cur = CONN.execute(
            "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            _row(rec, now=_now()),
        )
        seeded.append((cur.fetchone()["id"], sec))
    print(f"[phase 2] seeded {len(seeded)} 母版 base clauses: {seeded}")

    # === Phase 1: re-tag old base (21 示范文本) -> tagged + scenario ===
    total = 0
    for doc in docs:
        if doc == MOTHER_TITLE:
            continue
        scen = to_scenario(doc)
        cur = CONN.execute(
            "UPDATE clauses SET "
            "  tags = jsonb_set(jsonb_set(tags, '{source}', '\"tagged\"', true), "
            "                        '{scenario}', to_jsonb(%s::text), true), "
            "  updated_at = %s "
            "WHERE contract_type='sale' AND tags->>'source'='base' AND source_doc_title=%s",
            (scen, _now(), doc),
        )
        total += cur.rowcount
        print(f"  {cur.rowcount:3d}  {doc}  -> scenario={scen}")
    print(f"[phase 1] re-tagged {total} clauses base->tagged+scenario")

    CONN.commit()
    print("[done] committed")

    # === verify ===
    base_n = CONN.execute("SELECT COUNT(*) n FROM clauses WHERE contract_type='sale' AND tags->>'source'='base'").fetchone()["n"]
    tagged_n = CONN.execute("SELECT COUNT(*) n FROM clauses WHERE contract_type='sale' AND tags->>'source'='tagged'").fetchone()["n"]
    scen_n = CONN.execute("SELECT COUNT(DISTINCT tags->>'scenario') n FROM clauses WHERE contract_type='sale' AND tags->>'source'='tagged' AND tags->>'scenario' IS NOT NULL").fetchone()["n"]
    print(f"[verify] sale base={base_n}  tagged={tagged_n}  distinct tagged scenarios={scen_n}")
    CONN.close()


if __name__ == "__main__":
    main()
