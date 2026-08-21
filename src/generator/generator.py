"""DOCX generation from Markdown contract content with slot support.

The renderer is intentionally lightweight: it covers the Markdown structures
that appear in the project's contract templates (``templates/*.md``) -
headings, bold/italic, bullet and numbered lists, horizontal rules, and
paragraphs. Slot tokens (``{{slot_name}}``) in the content are rendered as
highlighted placeholders or pre-filled values.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.text.paragraph import Paragraph

from .slots import (
    SLOT_PATTERN,
    _open_document,
    set_run_text,
    slot_token,
)

__all__ = ["create_docx", "add_slot"]

# ponytail: 宋体/黑体 read correctly in Word/Windows; the container's LibreOffice
# needs matching CJK glyphs installed (or a Noto fallback) for PDF. See tasks 6.1.
_BODY_FONT = "宋体"
_HEADING_FONT = "黑体"
_BODY_SIZE = Pt(12)  # 小四
_HEADING_SIZES = {"Heading 1": Pt(22), "Heading 2": Pt(16), "Heading 3": Pt(14)}
_LINE_SPACING = 1.5
_FIRST_LINE_CHARS = 200  # 2 chars, in hundredths of a char

_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.*)$")
# Inline tokens: a slot, a **bold** span, or an *italic* span. The slot name
# pattern mirrors ``SLOT_PATTERN`` (Unicode ``\w``) so CJK slots like
# ``{{甲方名称}}`` are recognized as slots (highlighted/fillable), not just the
# Latin ones (``{{party_a}}``).
_INLINE_RE = re.compile(
    r"\{\{\s*[\w][\w-]*\s*\}\}"  # slot
    r"|\*\*[^*]+\*\*"  # **bold**
    r"|\*[^*]+\*"  # *italic*
)


def _parse_inline(text: str) -> list[dict]:
    """Split ``text`` into ordered segments: plain, slot, bold, or italic."""
    segments: list[dict] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            segments.append({"text": text[pos:m.start()], "bold": False, "italic": False, "slot": None})
        tok = m.group(0)
        if tok.startswith("{{"):
            segments.append(
                {"text": tok, "bold": False, "italic": False, "slot": SLOT_PATTERN.match(tok).group(1)}
            )
        elif tok.startswith("**"):
            segments.append({"text": tok[2:-2], "bold": True, "italic": False, "slot": None})
        else:  # *italic*
            segments.append({"text": tok[1:-1], "bold": False, "italic": True, "slot": None})
        pos = m.end()
    if pos < len(text):
        segments.append({"text": text[pos:], "bold": False, "italic": False, "slot": None})
    return segments


def _apply_inline(run, seg: dict) -> None:
    if seg["bold"]:
        run.bold = True
    if seg["italic"]:
        run.italic = True


def _render_inline(paragraph: Paragraph, text: str, slots, highlight_slots: bool = True) -> None:
    """Add runs for ``text``, rendering slots as placeholders or filled values."""
    for seg in _parse_inline(text):
        if seg["slot"] is not None:
            name = seg["slot"]
            value = None if slots is None else slots.get(name)
            if value is not None:
                run = paragraph.add_run()
                _apply_inline(run, seg)
                set_run_text(run, str(value))
            else:
                run = paragraph.add_run(slot_token(name))
                if highlight_slots:
                    run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                _apply_inline(run, seg)
        elif seg["text"]:
            run = paragraph.add_run(seg["text"])
            _apply_inline(run, seg)


def _add_horizontal_rule(document) -> None:
    paragraph = document.add_paragraph()
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    pbdr.append(bottom)
    pPr.append(pbdr)


def _set_eastasia_font(run_or_style, name: str) -> None:
    """Set both Latin and CJK faces on a run or style.

    ``.font.name`` only writes ``w:rFonts/@w:ascii``+``@w:hAnsi`` (Latin); CJK
    glyphs read ``@w:eastAsia``, which must be set separately or Chinese text
    keeps the default face.
    """
    run_or_style.font.name = name  # ascii + hAnsi
    rPr = run_or_style.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), name)


def _set_first_line_chars(style, chars: int = _FIRST_LINE_CHARS) -> None:
    """2-char first-line indent (scales with font size, unlike fixed twips)."""
    pPr = style.element.get_or_add_pPr()
    ind = pPr.get_or_add_ind()
    ind.set(qn("w:firstLineChars"), str(chars))
    ind.set(qn("w:firstLine"), str(chars * 240 // 100))  # twips fallback


def _set_heading(style, name: str, size, center: bool) -> None:
    style.font.bold = False  # 黑体 is already a heavy face
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.font.size = size
    _set_eastasia_font(style, name)
    if center:
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _apply_zh_document_style(document) -> None:
    """A4 page, 宋体 body with 2-char indent + line spacing, 黑体 headings."""
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(37)
    section.bottom_margin = Mm(35)
    section.left_margin = Mm(28)
    section.right_margin = Mm(26)

    normal = document.styles["Normal"]
    normal.font.size = _BODY_SIZE
    _set_eastasia_font(normal, _BODY_FONT)
    normal.paragraph_format.line_spacing = _LINE_SPACING
    _set_first_line_chars(normal)

    for i, heading in enumerate(("Heading 1", "Heading 2", "Heading 3"), start=1):
        _set_heading(document.styles[heading], _HEADING_FONT, _HEADING_SIZES[heading], center=(i == 1))


def _set_table_borderless(table) -> None:
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        borders.append(el)
    table._tbl.tblPr.append(borders)


def _signature_cells(lines: list[str]) -> list[list[str]]:
    """Group signature lines into 2 columns (party blocks or alternating slots)."""
    cells: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if "签字/盖章" in ln:
            if cur:
                cells.append(cur)
            cur = [ln]
        elif "日期" in ln and cur:
            cur.append(ln)  # a 日期 line belongs to the party block above it
        else:
            if cur:
                cells.append(cur)
                cur = []
            cells.append([ln])
    if cur:
        cells.append(cur)
    return cells


def _fill_signature_cell(cell, lines, slots, highlight_slots) -> None:
    first = True
    for ln in lines:
        para = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _render_inline(para, ln, slots, highlight_slots)


def _render_signature_block(document, lines, slots, highlight_slots) -> None:
    """Render trailing signature lines as a borderless 2-column, right-aligned table."""
    cells = _signature_cells(lines)
    table = document.add_table(rows=0, cols=2)
    _set_table_borderless(table)
    for k in range(0, len(cells), 2):
        left = cells[k]
        right = cells[k + 1] if k + 1 < len(cells) else [""]
        row = table.add_row()
        _fill_signature_cell(row.cells[0], left, slots, highlight_slots)
        _fill_signature_cell(row.cells[1], right, slots, highlight_slots)


def _collect_signature_lines(lines: list[str], start: int) -> tuple[list[str], int]:
    """Collect stripped, non-empty lines from ``start`` until a heading/HR."""
    sig: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _HEADING_RE.match(line) or _HR_RE.match(line):
            break
        sig.append(line)
        i += 1
    return sig, i


def _render_markdown(document, content: str, slots, highlight_slots: bool = True) -> None:
    lines = content.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _HR_RE.match(line):
            _add_horizontal_rule(document)
            i += 1
        elif m := _HEADING_RE.match(line):
            is_signature = "签署信息" in m.group(2)
            paragraph = document.add_paragraph(style=f"Heading {len(m.group(1))}")
            _render_inline(paragraph, m.group(2), slots, highlight_slots)
            i += 1
            if is_signature:
                sig_lines, i = _collect_signature_lines(lines, i)
                if sig_lines:
                    _render_signature_block(document, sig_lines, slots, highlight_slots)
        elif "签字/盖章" in line:
            sig_lines, i = _collect_signature_lines(lines, i)
            _render_signature_block(document, sig_lines, slots, highlight_slots)
        elif m := _BULLET_RE.match(line):
            paragraph = document.add_paragraph(style="List Bullet")
            _render_inline(paragraph, m.group(1), slots, highlight_slots)
            i += 1
        elif m := _NUMBERED_RE.match(line):
            paragraph = document.add_paragraph(style="List Number")
            _render_inline(paragraph, m.group(1), slots, highlight_slots)
            i += 1
        else:
            paragraph = document.add_paragraph()
            _render_inline(paragraph, line, slots, highlight_slots)
            i += 1


def create_docx(content, output_path, *, slots=None, title=None, highlight_slots: bool = True):
    """Render Markdown ``content`` to a ``.docx`` at ``output_path``.

    ``slots`` (optional) maps slot names to values: a non-None value fills the
    ``{{slot}}`` token at generation time; a missing or None entry leaves a
    placeholder. ``title`` (optional) is rendered as a Heading 1 before the
    content. ``highlight_slots`` (default True) yellow-highlights unfilled
    placeholders; pass False for a clean, fillable "成品" without the highlight.
    Parent directories are created as needed. Returns the resolved
    :class:`~pathlib.Path` to the written file.
    """
    document = Document()
    _apply_zh_document_style(document)
    if title:
        heading = document.add_paragraph(style="Heading 1")
        _render_inline(heading, str(title), slots, highlight_slots)
    _render_markdown(document, content, slots, highlight_slots)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))
    return out


def add_slot(doc, slot_name, *, label=None, value=None):
    """Append a slot paragraph to ``doc`` (a path or open document).

    With ``label`` the paragraph reads ``label: {{slot_name}}`` (or just
    ``{{slot_name}}``). The placeholder is highlighted unless ``value`` is
    given, in which case the slot is filled immediately. When ``doc`` is a path
    the file is saved in place.
    """
    document = _open_document(doc)
    paragraph = document.add_paragraph()
    if label:
        paragraph.add_run(f"{label}: ")
    if value is not None:
        run = paragraph.add_run()
        set_run_text(run, str(value))
    else:
        run = paragraph.add_run(slot_token(slot_name))
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    if isinstance(doc, (str, Path)):
        document.save(str(doc))
    return None
