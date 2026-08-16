"""Quick pre-P2 sanity check: confirm DB reachability + count tagged-ready clauses."""
import os
from src.eval.db import connect, close_shared_conn
from src.clauses.tag_review import is_assembly_ready

c = connect()
row = c.execute("SELECT count(*) AS n FROM clauses WHERE tags->>'source'='tagged'").fetchone()
print("tagged total:", row["n"])

# Count tagged-ready (non-empty body, no rejected tag_review dim)
rows = c.execute(
    "SELECT id, body, tag_review FROM clauses "
    "WHERE tags->>'source'='tagged' AND body IS NOT NULL AND body <> '' "
    "ORDER BY id"
).fetchall()
ready = 0
for r in rows:
    tr = r["tag_review"] or {}
    if tr and any(v == "rejected" for v in tr.values()):
        continue
    ready += 1
print("tagged-ready (P2 candidates):", ready)
print("sample of 3:", [r["id"] for r in rows[:3]])

# How many already have audit result files?
import glob, pathlib
files = glob.glob("output/audit/*.json")
print("existing result files:", len(files))

# How many tagged-ready already audited (have a result file)?
audited_tagged = 0
for f in files:
    import json
    with open(f) as fh:
        d = json.load(fh)
    if d.get("contract_type") and d.get("clause_id"):
        # check if this clause is tagged-ready
        cl = c.execute(
            "SELECT tags->>'source' AS src, body, tag_review FROM clauses WHERE id=%s",
            (d["clause_id"],),
        ).fetchone()
        if cl and cl["src"] == "tagged" and cl["body"]:
            tr = cl["tag_review"] or {}
            if not (tr and any(v == "rejected" for v in tr.values())):
                audited_tagged += 1
print("tagged-ready already audited:", audited_tagged)
close_shared_conn()
