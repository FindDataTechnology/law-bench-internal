"""Tests for the underline + slot-style rendering (``add-contract-underlines``)."""

from docx import Document
from docx.oxml.ns import qn

from src.generator import create_docx, find_slots


def _doc(path):
    return Document(str(path))


def _underlined_runs(para):
    """Runs in ``para`` that carry a ``<w:u>`` underline element."""
    out = []
    for r in para.runs:
        rPr = r._r.find(qn("w:rPr"))
        if rPr is not None and rPr.find(qn("w:u")) is not None:
            out.append(r)
    return out


def test_blank_run_real_underline(tmp_path):
    # 5.1: a literal ____ blank becomes an underlined space run, no `_` chars.
    p = create_docx("甲方：____________________", tmp_path / "c.docx")
    para = _doc(p).paragraphs[0]
    assert "_" not in para.text  # no literal underscore characters remain
    assert _underlined_runs(para)  # at least one underlined run


def test_slot_name_underscore_preserved(tmp_path):
    # 5.2: underscores inside a {{slot}} name are not eaten by _split_underlines.
    p = create_docx("甲方：{{party_a}}", tmp_path / "c.docx")
    para = _doc(p).paragraphs[0]
    assert find_slots(p) == ["party_a"]
    assert "{{party_a}}" in para.text


def test_inline_underline_span(tmp_path):
    # 5.3: _text_ renders the inner text as an underlined run; surroundings not.
    p = create_docx("违约金 _万分之五_ 约定", tmp_path / "c.docx")
    para = _doc(p).paragraphs[0]
    underlined = [r.text for r in _underlined_runs(para)]
    assert "万分之五" in underlined
    for r in para.runs:
        if r.text.strip() and r.text.strip() != "万分之五":
            rPr = r._r.find(qn("w:rPr"))
            assert rPr is None or rPr.find(qn("w:u")) is None


def test_slot_style_underline(tmp_path):
    # 5.4: slot_style="underline" emits a blank, no {{}} text, unfindable.
    p = create_docx("甲方：{{甲方名称}}", tmp_path / "c.docx", slot_style="underline")
    para = _doc(p).paragraphs[0]
    assert "{{" not in para.text and "}}" not in para.text
    assert _underlined_runs(para)
    assert find_slots(p) == []


def test_slot_style_highlight_default(tmp_path):
    # 5.5: default slot_style highlights the token.
    p = create_docx("甲方：{{party_a}}", tmp_path / "c.docx")
    para = _doc(p).paragraphs[0]
    highlighted = [
        r.text for r in para.runs
        if r._r.find(qn("w:rPr")) is not None
        and r._r.find(qn("w:rPr")).find(qn("w:highlight")) is not None
    ]
    assert "{{party_a}}" in highlighted


def test_slot_style_literal(tmp_path):
    # 5.6: slot_style="literal" keeps token text, no highlight, no underline.
    p = create_docx("甲方：{{party_a}}", tmp_path / "c.docx", slot_style="literal")
    para = _doc(p).paragraphs[0]
    assert "{{party_a}}" in para.text
    for r in para.runs:
        rPr = r._r.find(qn("w:rPr"))
        assert rPr is None or rPr.find(qn("w:highlight")) is None


def test_heading_spacing(tmp_path):
    # 5.7: Heading 1/2/3 styles have non-zero space_before and space_after.
    p = create_docx("# H1\n\n## H2\n\n### H3", tmp_path / "c.docx")
    doc = _doc(p)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        pf = doc.styles[name].paragraph_format
        assert pf.space_before is not None and pf.space_before.pt > 0
        assert pf.space_after is not None and pf.space_after.pt > 0
