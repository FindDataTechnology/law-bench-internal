"""Throwaway regression gate for the generator-rules-integration change.

For every contract type, calls generate_contract_assembled(format="markdown")
and reports whether it assembles + passes the coherence gate. The gate PASSES
iff all original-43 types assemble+coherent. Cat B (23 new types) is a sanity
check (non-blocking).
"""

from __future__ import annotations

import sys
import traceback

CAT_B = {
    "mortgage", "pledge", "will", "prenup", "marital-property", "divorce",
    "adoption", "legacy-support", "elderly-support", "estate-division",
    "debt-transfer", "debt-restructuring", "settlement", "accident-settlement",
    "nda", "non-compete", "internship", "training", "labor-service",
    "housekeeping", "shareholders", "investment", "shop-transfer",
}


def main() -> int:
    from src.clauses.assemble import generate_contract_assembled
    from src.clauses.coherence import CoherenceError
    from src.contracts.templates import list_contract_types
    from src.eval.db import connect

    db = connect(None)
    all_types = [t["key"] for t in list_contract_types()]
    orig = [t for t in all_types if t not in CAT_B]
    cat_b = [t for t in all_types if t in CAT_B]

    print(f"Total types: {len(all_types)}  original: {len(orig)}  cat_b: {len(cat_b)}")
    assert len(orig) == 43, f"expected 43 original, got {len(orig)}"
    assert len(cat_b) == 23, f"expected 23 cat_b, got {len(cat_b)}"

    orig_failures: list[tuple[str, str]] = []
    catb_failures: list[tuple[str, str]] = []

    def _try(label: str, types: list[str], sink: list[tuple[str, str]]) -> int:
        ok = 0
        for t in types:
            try:
                res = generate_contract_assembled(t, format="markdown", db=db)
                # sanity: body_text should be non-empty
                body = (res or {}).get("body_text") or ""
                if not body.strip():
                    sink.append((t, "OK but empty body_text"))
                    print(f"  [{label}] {t:30s} WARN  empty body")
                    continue
                ok += 1
                print(f"  [{label}] {t:30s} OK    body={len(body)}c slots={len(res.get('slots') or [])}")
            except CoherenceError as e:
                sink.append((t, f"CoherenceError: {e}"))
                print(f"  [{label}] {t:30s} FAIL  CoherenceError: {e}")
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                sink.append((t, msg))
                print(f"  [{label}] {t:30s} FAIL  {msg}")
                # print abbreviated traceback to stderr for debugging
                tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                sys.stderr.write("".join(tb_lines[:8]) + "\n")
        return ok

    print("\n=== ORIGINAL 43 (gate-critical) ===")
    orig_ok = _try("ORIG", orig, orig_failures)

    print("\n=== CAT B 23 (sanity) ===")
    catb_ok = _try("CATB", cat_b, catb_failures)

    print("\n=== SUMMARY ===")
    print(f"ORIGINAL 43: {orig_ok}/43 assembled+coherent")
    if orig_failures:
        print("  FAILURES:")
        for t, msg in orig_failures:
            print(f"    - {t}: {msg}")
    print(f"CAT B 23:    {catb_ok}/23 assembled+coherent (sanity)")
    if catb_failures:
        print("  FAILURES (non-blocking):")
        for t, msg in catb_failures:
            print(f"    - {t}: {msg}")

    gate_passes = len(orig_failures) == 0
    print(f"\nGATE: {'PASS' if gate_passes else 'FAIL'} (original-43 all assemble+coherent)")
    return 0 if gate_passes else 1


if __name__ == "__main__":
    sys.exit(main())
