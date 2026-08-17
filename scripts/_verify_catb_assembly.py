"""Verify all 23 Category B types assemble + pass the coherence gate (markdown).

Throwaway. Run from law-template root with database_url exported.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.clauses.assemble import generate_contract_assembled
from src.clauses.coherence import CoherenceError
from src.eval.db import connect

CAT_B = [
    "mortgage", "pledge", "will", "prenup", "marital-property",
    "divorce", "adoption", "legacy-support", "elderly-support",
    "estate-division", "debt-transfer", "debt-restructuring",
    "settlement", "accident-settlement", "nda", "non-compete",
    "internship", "training", "labor-service", "housekeeping",
    "shareholders", "investment", "shop-transfer",
]


def main() -> None:
    db = connect(None)
    total = db.execute("SELECT count(*) AS c FROM clauses").fetchone()["c"]
    print(f"clauses table now: {total} rows\n")
    print(f"{'type':<22}{'status':<8}{'slots':>6}{'instr':>6}{'heur':>6}")
    ok = 0
    fail: list[tuple[str, str]] = []
    for key in CAT_B:
        try:
            r = generate_contract_assembled(key, format="markdown", db=db)
            heur = len(r["diagnostics"]["heuristic_sections"])
            print(f"{key:<22}{'OK':<8}{len(r['slots']):>6}{len(r['instructions']):>6}{heur:>6}")
            ok += 1
        except CoherenceError as e:
            print(f"{key:<22}{'FAIL':<8}{str(e)[:60]}")
            fail.append((key, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"{key:<22}{'ERR':<8}{type(e).__name__}: {str(e)[:50]}")
            fail.append((key, f"{type(e).__name__}: {e}"))
    print(f"\n{ok}/{len(CAT_B)} assembled + passed coherence")
    if fail:
        print("FAILURES:")
        for k, msg in fail:
            print(f"  {k}: {msg}")


if __name__ == "__main__":
    main()
