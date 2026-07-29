"""Document generation: DOCX creation with slots + DOCX -> PDF conversion.

Public API:

- :func:`create_docx` - render Markdown content to a ``.docx`` with slots.
- :func:`add_slot` - append a slot to an existing document.
- :func:`fill_slots` / :func:`find_slots` / :func:`slot_token` - slot helpers.
- :func:`docx_to_pdf` / :func:`create_pdf` / :func:`get_converter` - PDF output.
"""

from __future__ import annotations

from pathlib import Path

from .converter import (
    ConverterNotAvailableError,
    Docx2PdfConverter,
    LibreOfficeConverter,
    PdfConverter,
    docx_to_pdf,
    get_converter,
)
from .generator import add_slot, create_docx
from .slots import SLOT_PATTERN, SlotValueError, fill_slots, find_slots, slot_token

__all__ = [
    "SLOT_PATTERN",
    "SlotValueError",
    "ConverterNotAvailableError",
    "PdfConverter",
    "LibreOfficeConverter",
    "Docx2PdfConverter",
    "slot_token",
    "find_slots",
    "fill_slots",
    "create_docx",
    "add_slot",
    "docx_to_pdf",
    "create_pdf",
    "get_converter",
]


def create_pdf(content, output_path, *, slots=None, title=None, backend=None) -> Path:
    """Generate a PDF from Markdown ``content`` and return its path.

    Builds an intermediate DOCX via :func:`create_docx` alongside the PDF
    (``output_path`` with a ``.docx`` extension), then converts it to PDF via
    :func:`docx_to_pdf`.
    """
    pdf_path = Path(output_path)
    docx_path = pdf_path.with_suffix(".docx")
    create_docx(content, docx_path, slots=slots, title=title)
    return docx_to_pdf(docx_path, output_path=str(pdf_path), backend=backend)
