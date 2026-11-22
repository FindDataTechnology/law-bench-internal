"""Deterministic checkers for the ERP line (``kind='account'``).

Registration happens at import time: importing this module installs the checkers
below into ``src.bench.data_checks.register_checker``. Every checker is pure and
deterministic — no LLM, no network, no filesystem, and **no cross-table query**
(a checker only sees the one unit dict it is handed).

These are **validity invariants**, not statistical criteria: on clean data every
account passes, and that is the correct outcome — the value is that a future bad
import fails loudly. The project's ``criterion-must-fire-on-real-data`` constraint
explicitly exempts correctness assertions of this shape; the discrimination it
does demand is proven in ``tests/test_erp_checks.py`` with a real-format bad unit
(correctness assertion on input X → wrong output), and the ERP production
distribution is recorded in the change's ``acceptance.md``.

What is judged (each reads only the unit's own ``attrs``):

- 映射目标在通用科目闭集内 — ``account.attrs.maps_to`` ∈ the kernel's 12-code
  universal preset. A mapping onto a code the kernel does not have is a broken
  promise, not a mapping. **Nothing else in the platform checks this** — the
  quality-ratio channel measures grounding / evidence / crosswalk coverage, not
  mapping-target validity — so this adds genuine coverage.
- 科目带 evidence 锚点 — ``account.attrs.evidence`` present with quote+source.
  A per-unit gate complementing the domain-level ``quality.evidence`` ratio: the
  ratio says "87% carry evidence", this says *which* one does not and can gate a
  specific import.

What is deliberately **not** judged here, and why:

- The four crosswalk/账务 criteria (映射不冒充已复核, 账务事实只在内核, 回写只出
  proposal, 回写科目白名单, 外部系统接通三态) are already computed by the
  quality-ratio channel (``quality.crosswalk_gaps`` reports ``unconfirmed`` /
  ``dangling`` / ``stale``) or need cross-table/cross-system evidence a single
  unit cannot carry. Re-implementing them as checkers would be a second source of
  truth for one measurement — the platform keeps one口径 per metric.
"""

from __future__ import annotations

from typing import Any

from src.bench.data_checks import CheckResult, register_checker

#: Knowledge-unit kind this pack evaluates.
ACCOUNT_KIND = "account"

#: ``universal_accounts`` v1 (12 codes), from
#: ``fd-erp-ledger-mcp/fd_erp_ledger_mcp/migrations/0002_universal_accounts.sql``.
#:
#: shortcut: the preset code list is a copy of the kernel migration, not read from
#: it — bump it when the kernel adds accounts. Upgrade path: a read-only preset
#: surface on the kernel's tool face.
UNIVERSAL_ACCOUNTS_V1: frozenset[str] = frozenset(
    {"1000", "1100", "1200", "1300", "2000", "2100", "3000", "3100",
     "4000", "5000", "5100", "5200"}
)


def _attr(unit: dict, name: str) -> Any:
    return (unit.get("attrs") or {}).get(name)


def check_account_maps_to_preset(unit: dict) -> CheckResult:
    """映射目标在通用科目闭集内：``attrs.maps_to`` 必须落在 12 码预设内。"""
    maps_to = _attr(unit, "maps_to")
    ok = isinstance(maps_to, str) and maps_to in UNIVERSAL_ACCOUNTS_V1
    detail = f"maps_to={maps_to!r} allowed={sorted(UNIVERSAL_ACCOUNTS_V1)}"
    return CheckResult(name="account-maps-to-preset", passed=ok, detail=detail)


def check_account_evidence_anchor(unit: dict) -> CheckResult:
    """科目带 evidence 锚点：``attrs.evidence`` 必须是含 quote/source 的映射。

    没有依据的科目「不可回源」——它读起来像本体，却指不回任何 pack 文件。
    """
    evidence = _attr(unit, "evidence")
    ok = (
        isinstance(evidence, dict)
        and bool(evidence.get("quote"))
        and bool(evidence.get("source_path"))
    )
    detail = (
        "evidence ok"
        if ok
        else f"evidence={'present but incomplete' if isinstance(evidence, dict) else repr(evidence)}"
    )
    return CheckResult(name="account-evidence-anchor", passed=ok, detail=detail)


register_checker(ACCOUNT_KIND, "account-maps-to-preset", check_account_maps_to_preset)
register_checker(ACCOUNT_KIND, "account-evidence-anchor", check_account_evidence_anchor)
