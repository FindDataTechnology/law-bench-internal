"""Count the actual P2-eligible set after the scenario filter."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(override=True)
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.eval.db import connect, close_shared_conn

c = connect()

# P2-eligible = scenario-bearing + non-empty body + no rejected dim
row = c.execute(
    "SELECT count(*) AS n FROM clauses "
    "WHERE tags->>'source' = 'tagged' "
    "  AND body IS NOT NULL AND body <> '' "
    "  AND tags ? 'scenario' "
    "  AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'rejected')"
).fetchone()
print(f"P2_eligible (scenario-bearing, non-empty, non-rejected) = {row['n']}")

# per-type breakdown of P2-eligible
rows = c.execute(
    "SELECT contract_type, count(*) AS n FROM clauses "
    "WHERE tags->>'source' = 'tagged' "
    "  AND body IS NOT NULL AND body <> '' "
    "  AND tags ? 'scenario' "
    "  AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'rejected') "
    "GROUP BY contract_type ORDER BY n DESC"
).fetchall()
print("\nper-type P2-eligible:")
for r in rows:
    print(f"  {r['contract_type']:20s} {r['n']}")

# orphan census: scenario-less tagged, non-rejected (never enter assembly)
orphan = c.execute(
    "SELECT count(*) AS n FROM clauses "
    "WHERE tags->>'source' = 'tagged' "
    "  AND body IS NOT NULL AND body <> '' "
    "  AND NOT tags ? 'scenario' "
    "  AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'rejected')"
).fetchone()
print(f"\norphan_scenarioless_tagged (never enter assembly) = {orphan['n']}")

close_shared_conn()
