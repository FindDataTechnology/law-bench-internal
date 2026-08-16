"""P2 readiness diagnostic — how many tagged clauses will the P2 audit load?"""
import os, sys, json, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(override=True)
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.eval.db import connect, close_shared_conn

c = connect()

# 1. tagged total
tot = c.execute("SELECT count(*) AS n FROM clauses WHERE tags->>'source'='tagged'").fetchone()
print(f"tagged_total={tot['n']}")

# 2. tagged with non-empty body
nb = c.execute(
    "SELECT count(*) AS n FROM clauses WHERE tags->>'source'='tagged' "
    "AND body IS NOT NULL AND body <> ''"
).fetchone()
print(f"tagged_nonempty_body={nb['n']}")

# 3. tag_review status breakdown for tagged (non-empty body)
rows = c.execute(
    "SELECT id, tag_review, body FROM clauses WHERE tags->>'source'='tagged' "
    "AND body IS NOT NULL AND body <> ''"
).fetchall()
rejected = 0          # has at least one 'rejected' dim
all_approved = 0      # every dim approved (assembly-ready)
has_pending = 0       # at least one pending, none rejected
empty_review = 0      # tag_review is null or {}
for r in rows:
    tr = r["tag_review"] or {}
    if not tr:
        empty_review += 1
        continue
    vals = list(tr.values())
    if any(v == "rejected" for v in vals):
        rejected += 1
    elif all(v == "approved" for v in vals):
        all_approved += 1
    else:
        has_pending += 1
print(f"tagged_nonempty: rejected={rejected} all_approved={all_approved} has_pending={has_pending} empty_review={empty_review}")
print(f"P2_loadable (non-empty body AND no rejected dim) = {len(rows) - rejected}")

# 4. sample a few tagged clauses to see their tag_review shape
sample = c.execute(
    "SELECT id, contract_type, section, tag_review, left(body, 60) AS body_head "
    "FROM clauses WHERE tags->>'source'='tagged' AND body IS NOT NULL AND body <> '' "
    "ORDER BY id LIMIT 5"
).fetchall()
for s in sample:
    print(f"  sample id={s['id']} type={s['contract_type']} sec={s.get('section')} review={json.dumps(s['tag_review'], ensure_ascii=False)} head={s['body_head']!r}")

# 5. how many tagged clauses already audited (result file exists)
files = glob.glob("output/audit/*.json")
audited_ids = set()
for f in files:
    try:
        with open(f) as fh:
            d = json.load(fh)
        audited_ids.add(d.get("clause_id"))
    except Exception:
        pass
tagged_audited = 0
for r in rows:
    if r["id"] in audited_ids:
        tagged_audited += 1
print(f"result_files_total={len(files)} tagged_already_audited={tagged_audited}")

close_shared_conn()
