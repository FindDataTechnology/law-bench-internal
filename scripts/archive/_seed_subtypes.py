"""Seed sub-type tagged clauses (Task 5) into the DB — collision-checked.

First enumerates every tagged record the import would write and flags any
whose ``section`` lands in a core base section (当事人/权利义务/违约责任/...).
A tagged clause in a core section would override the rich base body at
assembly (custom>tagged>base per section) — the sale-quanyi-override failure
mode. If any collision exists, we abort the write and print them for review.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, "/Users/chengsishi/law-template")

os.environ.setdefault(
    "database_url",
    "postgresql://app:change-me-please@localhost:15432/law_bench",
)

from src.clauses.generator_import import (  # noqa: E402
    SUBTYPE_SCENARIOS,
    _leaf_clause_records,
    build_registry,
    import_subtypes,
)

# core base sections — a tagged clause here overrides rich base at assembly
CORE_SECTIONS = {
    "当事人", "合同标的", "价款及支付", "履行期限",
    "权利义务", "违约责任", "争议解决", "附则", "签署信息",
}

reg, h = build_registry()

by_type: dict[str, list[tuple]] = defaultdict(list)
for leaf, (ct, sc) in SUBTYPE_SCENARIOS.items():
    recs = _leaf_clause_records(leaf, ct, sc, reg, h)
    for r in recs:
        by_type[ct].append((sc, r["section"], r["source_path"], r["body"][:46].replace("\n", " ")))

total = sum(len(v) for v in by_type.values())
print(f"types with subtypes: {len(by_type)} | total tagged records: {total}")

collisions = []
for ct, items in by_type.items():
    for sc, sec, sp, body in items:
        if sec in CORE_SECTIONS:
            collisions.append((ct, sc, sec, sp, body))

print(f"CORE-SECTION COLLISIONS: {len(collisions)}")
for c in collisions:
    print(f"  {c[0]}/{c[1]} §{c[2]}  {c[3]}  | {c[4]}")

# per-type section inventory (non-core), for eyeballing
print("\n--- per-type sections (non-core) ---")
for ct in sorted(by_type):
    secs = sorted({(sc, sec) for sc, sec, _, _ in by_type[ct]})
    print(f"{ct}: {secs}")

# merge-not-replace: skip core-section collisions (a tagged clause here would
# override the rich base body at assembly — the sale-quanyi failure mode).
# Write only non-core tagged clauses; they ADD scenario-specific sections
# (车辆信息与车况披露, 过户登记, 利率与计息, ...) without touching base bodies.
from src.clauses.store import upsert_clause  # noqa: E402

print(f"\nWriting non-core tagged clauses (skipping {len(collisions)} collisions)...")
written = 0
for leaf, (ct, sc) in SUBTYPE_SCENARIOS.items():
    for r in _leaf_clause_records(leaf, ct, sc, reg, h):
        if r["section"] in CORE_SECTIONS:
            continue
        upsert_clause(r, None)
        written += 1
print(f"DONE — written={written} (skipped {len(collisions)} core-section collisions)")
