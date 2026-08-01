"""Backfill: normalize existing clause bodies + slot_instructions to canonical slots.

Applies src.contracts.slot_ontology.normalize_body_slots /
normalize_instruction_names to every clause row, re-deriving body_hash from the
normalized body (so dedup stays consistent). law_refs are preserved.

Rollback snapshot -> output/_slotnorm_rollback.json (id -> old body/slot_instructions/body_hash).
Collisions on the (source_path, section, body_hash) unique index (two clauses that
normalize to the same body) are skipped + logged, not fatal.

Usage:
  PYTHONPATH=. python3 scripts/backfill_slot_normalization.py --dry-run
  PYTHONPATH=. python3 scripts/backfill_slot_normalization.py --apply
"""
from __future__ import annotations
import argparse, hashlib, json
from psycopg.types.json import Jsonb
from src.eval.db import connect
from src.contracts.slot_ontology import normalize_body_slots, normalize_instruction_names

try:
    from psycopg.errors import UniqueViolation
except Exception:
    UniqueViolation = Exception


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.apply):
        ap.error("pass --dry-run or --apply")

    conn = connect()
    conn.autocommit = True  # per-statement tx so a collision skips just that row
    rows = conn.execute(
        "SELECT id, contract_type, body, slot_instructions, body_hash FROM clauses WHERE body IS NOT NULL ORDER BY id"
    ).fetchall()

    rollback = {}
    changes = skipped = unchanged = 0
    sample = []
    for r in rows:
        ct = r["contract_type"]
        body = normalize_body_slots(r["body"], ct)
        si = normalize_instruction_names(r["slot_instructions"] or [], ct)
        body_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
        if body == r["body"] and si == (r["slot_instructions"] or []):
            unchanged += 1
            continue
        changes += 1
        rollback[str(r["id"])] = {"body": r["body"], "slot_instructions": r["slot_instructions"], "body_hash": r["body_hash"]}
        if len(sample) < 8:
            sample.append((r["id"], ct, (r["body"] or "")[:50], body[:50]))
        if args.apply:
            try:
                conn.execute(
                    "UPDATE clauses SET body=%s, slot_instructions=%s, body_hash=%s WHERE id=%s",
                    (body, Jsonb(si), body_hash, r["id"]),
                )
            except UniqueViolation:
                skipped += 1
                changes -= 1
                continue
    if args.apply:
        json.dump(rollback, open("output/_slotnorm_rollback.json", "w"), ensure_ascii=False, indent=1)

    print(f"total={len(rows)}  would_change={changes}  unchanged={unchanged}  skipped_collisions={skipped}")
    print("--- sample (id, type, before -> after) ---")
    for cid, ct, before, after in sample:
        print(f"  {cid} [{ct}] {before!r} -> {after!r}")
    if args.apply:
        print(f"[applied] rollback -> output/_slotnorm_rollback.json ({len(rollback)} entries)")
    conn.close()


if __name__ == "__main__":
    main()
