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
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .slots import (
    SLOT_PATTERN,
    _open_document,
    set_run_text,
    slot_token,
)

__all__ = ["create_docx", "add_slot"]

_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.*)$")
# Inline tokens: a slot, a **bold** span, or an *italic* span.
_INLINE_RE = re.compile(
    r"\{\{\s*[a-zA-Z_][\w-]*\s*\}\}"  # slot
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


def _render_inline(paragraph: Paragraph, text: str, slots) -> None:
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


def _render_markdown(document, content: str, slots) -> None:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _HR_RE.match(line):
            _add_horizontal_rule(document)
        elif m := _HEADING_RE.match(line):
            paragraph = document.add_paragraph(style=f"Heading {len(m.group(1))}")
            _render_inline(paragraph, m.group(2), slots)
        elif m := _BULLET_RE.match(line):
            paragraph = document.add_paragraph(style="List Bullet")
            _render_inline(paragraph, m.group(1), slots)
        elif m := _NUMBERED_RE.match(line):
            paragraph = document.add_paragraph(style="List Number")
            _render_inline(paragraph, m.group(1), slots)
        else:
            paragraph = document.add_paragraph()
            _render_inline(paragraph, line, slots)


def create_docx(content, output_path, *, slots=None, title=None):
    """Render Markdown ``content`` to a ``.docx`` at ``output_path``.

    ``slots`` (optional) maps slot names to values: a non-None value fills the
    ``{{slot}}`` token at generation time; a missing or None entry leaves a
    highlighted placeholder. ``title`` (optional) is rendered as a Heading 1
    before the content. Parent directories are created as needed. Returns the
    resolved :class:`~pathlib.Path` to the written file.
    """
    document = Document()
    if title:
        heading = document.add_paragraph(style="Heading 1")
        _render_inline(heading, str(title), slots)
    _render_markdown(document, content, slots)

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
