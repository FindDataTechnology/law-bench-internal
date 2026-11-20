"""Industry account mappings → ``maps_to`` crosswalks (change add-finance-erp-domain-slices).

The rules that matter, and why each one is pinned:

- **the target must be in the universal preset** — a mapping onto a code the
  kernel does not have is a broken promise that would only surface when someone
  queried a balance. Refused at plan time, naming the code;
- **verticals keep their own code prefixes** — `X-` / `R-` / `SC-` do not collide
  today, and if a later pack reused `X-0001` for a different account the import
  would silently overwrite a confirmed mapping. The assertion is that all 23
  near keys are distinct;
- **the near end is an account entity, written before the mapping** — the write
  path refuses a crosswalk whose near endpoint is absent, so the order is
  load-bearing rather than cosmetic.
"""

from __future__ import annotations

import json
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import import_account_mapping_crosswalks as importer  # noqa: E402

TEMPLATES = REPO_ROOT.parent / "fd-erp-vertical-templates" / "templates"


needs_erp_repo = pytest.mark.skipif(
    not TEMPLATES.is_dir(),
    reason="fd-erp-vertical-templates is a sibling checkout; without it there is "
           "nothing to import and no pack to fake",
)


# ------------------------------------------------------------------- planning


@needs_erp_repo
def test_every_industry_account_becomes_one_row():
    rows = importer.plans(TEMPLATES)
    counts = Counter(r["vertical"] for r in rows)
    assert counts == {"crossborder": 8, "restaurant-chain": 7, "supply-chain": 8}
    assert len(rows) == 23


@needs_erp_repo
def test_near_keys_are_distinct_across_verticals():
    """A shared code space would let the second vertical overwrite the first."""
    keys = [r["near_key"] for r in importer.plans(TEMPLATES)]
    assert len(set(keys)) == len(keys)


@needs_erp_repo
def test_every_target_resolves_in_the_universal_preset():
    for row in importer.plans(TEMPLATES):
        assert row["target"] in importer.UNIVERSAL_ACCOUNTS_V1


@needs_erp_repo
def test_unknown_target_is_refused_naming_the_code(tmp_path):
    """A bad mapping must fail the import before anything lands."""
    vertical = tmp_path / "crossborder"
    (vertical / "account-mapping").mkdir(parents=True)
    (vertical / "account-mapping" / "pack.json").write_text(json.dumps({
        "account_mapping": {
            "vertical": "crossborder",
            "universal_preset_version": "v1",
            "industry_accounts": [
                {"code": "X-0001", "name_zh": "测试", "name_en": "Test",
                 "maps_to": "5300", "kind": "expense"},
            ],
        }
    }), encoding="utf-8")

    with pytest.raises(importer.MappingError) as exc:
        importer.plans(tmp_path)
    assert "5300" in str(exc.value)


@needs_erp_repo
def test_mapping_carries_no_confidence():
    """The pack says "aligned", not "someone checked". Inventing a number would
    count as reviewed something nobody reviewed."""
    attrs = importer.attrs_for({
        "target": "4000", "name_zh": "平台销售收入",
        "vertical": "crossborder", "code": "X-0001",
    })
    assert "confidence" not in attrs
    assert attrs["relation"] == "maps_to"
    assert attrs["peer"] == {"kind": "external_id",
                             "system": importer.PEER_SYSTEM, "id": "4000"}


# --------------------------------------------------------------- the write path


@needs_erp_repo
def test_write_path_lands_the_entity_before_the_mapping(monkeypatch):
    """Order is load-bearing: the crosswalk write refuses an absent near end."""
    seq: list[tuple[str, str]] = []

    class FakeAuthoring:
        @staticmethod
        def authoring_create_unit(conn, **kw):
            seq.append(("unit", kw["external_key"]))
            return {}

        @staticmethod
        def authoring_create_crosswalk(conn, **kw):
            seq.append(("crosswalk", kw["external_key"]))
            return {}

        @staticmethod
        def authoring_live_keys(conn, **kw):
            return {"x"}

    fake_conn = types.SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(
        connect=lambda *a, **k: fake_conn,
        rows=types.SimpleNamespace(dict_row=None),
    ))

    import src.bench.authoring as real_authoring
    import src.bench.crosswalk as real_cw
    import src.bench.store as real_store
    import src.eval.db as real_edb
    import src.eval.store as real_eval_store
    monkeypatch.setattr(real_authoring, "authoring_create_unit",
                        FakeAuthoring.authoring_create_unit)
    monkeypatch.setattr(real_authoring, "authoring_create_crosswalk",
                        FakeAuthoring.authoring_create_crosswalk)
    monkeypatch.setattr(real_authoring, "authoring_live_keys",
                        FakeAuthoring.authoring_live_keys)
    monkeypatch.setattr(real_store, "get_knowledge_unit", lambda conn, **kw: None)
    monkeypatch.setattr(real_eval_store, "ensure_schema", lambda **kw: None)
    monkeypatch.setattr(real_edb, "_dsn", lambda: "postgresql://fake/db")
    monkeypatch.setattr(real_cw, "list_rows", lambda conn, namespace: [1])

    assert importer.main(["--domain", "erp"]) == 0

    units = [key for kind, key in seq if kind == "unit"]
    crosswalks = [key for kind, key in seq if kind == "crosswalk"]
    assert len(units) == 23 and len(crosswalks) == 23
    # Every mapping is preceded by its own entity.
    assert seq == [item for pair in zip(
        [("unit", k) for k in units], [("crosswalk", k) for k in crosswalks]
    ) for item in pair]


@needs_erp_repo
def test_dry_run_writes_nothing(monkeypatch, capsys):
    called = {"n": 0}
    fake_psycopg = types.SimpleNamespace(
        connect=lambda *a, **k: called.update(n=called["n"] + 1),
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    assert importer.main(["--dry-run"]) == 0
    assert called["n"] == 0
    out = capsys.readouterr().out
    assert "23 industry account(s)" in out
    assert "DRY-RUN" in out
