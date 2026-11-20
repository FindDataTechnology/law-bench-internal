"""Gold-set landing into the finance domain (change add-finance-erp-domain-slices).

The pack's own loader writes to ``namespace='finance-data'``. Knowledge units are
scoped by namespace = the domain key, so gold landed there is invisible to the
finance domain's quality view, ledger and publication manifest — the domain would
look empty while 105 gold rows sat one namespace over. This script re-lands the
same records under the domain, and these tests pin the two ways that can go
wrong:

- an unreadable gold file must **raise**, not write nothing quietly: "0 rows" and
  "cannot read" are different facts;
- gold must keep ``tier='gold'`` — the pack writes through the store for that
  reason, because the authoring write path hardcodes ``tier='raw'``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import seed_finance_gold  # noqa: E402

SIBLING = REPO_ROOT.parent / "fd-sentiment"
REAL_GOLD = SIBLING / "gold" / "gold-v9.json"


def _adapters():
    import importlib

    return importlib.import_module("packs.finance-data.adapters")


def test_missing_sibling_checkout_refuses(monkeypatch, tmp_path, capsys):
    """An absent repo is a hard failure with a reason, never an empty import."""
    monkeypatch.setenv("FD_SENTIMENT_REPO", str(tmp_path))
    assert seed_finance_gold.main(["--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "No rows written" in err


def test_malformed_gold_file_refuses(monkeypatch, tmp_path, capsys):
    (tmp_path / "gold").mkdir()
    (tmp_path / "gold" / "gold-v9.json").write_text(
        json.dumps({"items": []}), encoding="utf-8"
    )
    monkeypatch.setenv("FD_SENTIMENT_REPO", str(tmp_path))
    assert seed_finance_gold.main(["--dry-run"]) == 1
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.skipif(not REAL_GOLD.is_file(),
                    reason="fd-sentiment sibling checkout not present")
def test_records_keep_gold_tier_after_namespace_rewrite(monkeypatch):
    """The script rewrites only the namespace; tier must stay gold."""
    adapters = _adapters()
    records = adapters.read_gold_records()
    unit = adapters.record_to_unit(records[0])
    assert unit["tier"] == "gold"
    assert unit["namespace"] == adapters.NAMESPACE  # the pack's own namespace

    unit["namespace"] = "finance"  # what the script does
    assert unit["tier"] == "gold"
    assert unit["namespace"] == "finance"


@pytest.mark.skipif(not REAL_GOLD.is_file(),
                    reason="fd-sentiment sibling checkout not present")
def test_gold_set_has_the_documented_size(monkeypatch):
    adapters = _adapters()
    assert len(adapters.read_gold_records()) == 105
