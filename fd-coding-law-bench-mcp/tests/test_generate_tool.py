"""Tests for ``generate_contract_from_tags``.

Hermetic: the wrapped ``src.*`` functions are monkeypatched, so no DB, network,
LibreOffice, or template files are touched. These tests verify the tool's own
dispatch / param-mapping / ``current_tags`` logic.
"""

from __future__ import annotations

import pytest


def _skeleton_result(**over):
    base = {
        "docx_path": None,
        "pdf_path": "/tmp/sale.pdf",
        "slots": ["party_a"],
        "instructions": [{"name": "party_a"}],
        "laws": [{"name": "民法典"}],
    }
    base.update(over)
    return base


def _assembled_result(**over):
    base = {
        "docx_path": None,
        "pdf_path": "/tmp/employment.pdf",
        "slots": ["party_a"],
        "instructions": [],
        "law_refs": [{"name": "劳动合同法"}],
    }
    base.update(over)
    return base


def test_known_type_uses_skeleton_path(monkeypatch):
    import src.contracts as contracts_mod

    calls = {}

    def fake_generate(contract_type, *, format="pdf", out_dir=None):
        calls.update(contract_type=contract_type, format=format, out_dir=out_dir)
        return _skeleton_result()

    monkeypatch.setattr(contracts_mod, "generate_contract", fake_generate)

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    res = generate_contract_from_tags("sale", format="pdf")
    assert calls == {"contract_type": "sale", "format": "pdf", "out_dir": None}
    assert res["pdf_path"] == "/tmp/sale.pdf"
    assert "laws" in res
    assert "current_tags" not in res


def test_stance_routes_to_assembled(monkeypatch):
    import src.clauses.assemble as assemble_mod

    calls = {}

    def fake_assembled(
        contract_type,
        *,
        province=None,
        custom_clause_ids=None,
        stance=None,
        format="pdf",
        out_dir=None,
        db=None,
    ):
        calls.update(contract_type=contract_type, province=province, stance=stance, format=format)
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    res = generate_contract_from_tags("employment", stance="pro_a")
    assert calls["stance"] == "pro_a"
    assert calls["province"] is None
    assert "law_refs" in res


def test_tags_region_routes_to_assembled_with_province(monkeypatch):
    import src.clauses.assemble as assemble_mod

    calls = {}

    def fake_assembled(
        contract_type, *, province=None, custom_clause_ids=None, stance=None,
        format="pdf", out_dir=None, db=None,
    ):
        calls.update(province=province, stance=stance)
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    generate_contract_from_tags("sale", tags={"region": "吉林"})
    assert calls["province"] == "吉林"
    assert calls["stance"] is None


def test_include_current_tags_returns_vocab_with_temp_dim(monkeypatch):
    import src.clauses.tags as tags_mod
    import src.contracts as contracts_mod

    # Skip the DB merge; load_vocab_from_db becomes a no-op so the live
    # TAG_VOCAB (incl. the temp dim registered below) is what gets snapshotted.
    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    tags_mod.register_tag_dim("vam_mechanism", ["equity_adjust", "cash_compensation"])

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    res = generate_contract_from_tags("sale", include_current_tags=True)
    ct = res["current_tags"]
    for dim in ("stance", "strength", "risk", "mandatory"):
        assert dim in ct
    assert ct["vam_mechanism"] == ["equity_adjust", "cash_compensation"]


def test_include_current_tags_false_omits_field(monkeypatch):
    import src.contracts as contracts_mod

    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    res = generate_contract_from_tags("sale", include_current_tags=False)
    assert "current_tags" not in res


def test_unknown_type_propagates(monkeypatch):
    import src.contracts as contracts_mod
    from src.eval.errors import NotFoundError

    def boom(contract_type, *, format="pdf", out_dir=None):
        raise NotFoundError(f"unknown contract type: {contract_type!r}")

    monkeypatch.setattr(contracts_mod, "generate_contract", boom)

    from fd_coding_law_bench_mcp.tools.generate import generate_contract_from_tags

    with pytest.raises(NotFoundError):
        generate_contract_from_tags("not_a_real_type")
