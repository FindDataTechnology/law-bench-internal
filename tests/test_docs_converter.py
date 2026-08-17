"""Tests for the DOCX -> PDF converter (``src.generator.converter``)."""

import shutil

import pytest

from src.generator import (
    ConverterNotAvailableError,
    Docx2PdfConverter,
    LibreOfficeConverter,
    create_docx,
    docx_to_pdf,
    get_converter,
)

SOFFICE_AVAILABLE = shutil.which("soffice") is not None


def test_get_converter_default_is_libreoffice(monkeypatch):
    monkeypatch.delenv("DOCS_PDF_BACKEND", raising=False)
    assert isinstance(get_converter(), LibreOfficeConverter)


def test_get_converter_resolves_env_var(monkeypatch):
    monkeypatch.setenv("DOCS_PDF_BACKEND", "docx2pdf")
    assert isinstance(get_converter(), Docx2PdfConverter)


def test_get_converter_rejects_unknown_backend():
    with pytest.raises(ValueError):
        get_converter("weasyprint")


def test_docx_to_pdf_default_output_path(tmp_path):
    if not SOFFICE_AVAILABLE:
        pytest.skip("libreoffice (soffice) not installed")
    p = create_docx("# 标题", tmp_path / "c.docx")
    pdf = docx_to_pdf(p)
    assert pdf == tmp_path / "c.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0


def test_docx_to_pdf_explicit_output_path(tmp_path):
    if not SOFFICE_AVAILABLE:
        pytest.skip("libreoffice (soffice) not installed")
    p = create_docx("# 标题", tmp_path / "c.docx")
    pdf = docx_to_pdf(p, output_path=str(tmp_path / "final.pdf"))
    assert pdf == tmp_path / "final.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0


def test_converter_not_available_raises(tmp_path):
    p = create_docx("# 标题", tmp_path / "c.docx")
    converter = LibreOfficeConverter(binary="soffice-definitely-missing-xyz")
    with pytest.raises(ConverterNotAvailableError):
        converter.convert(p)
