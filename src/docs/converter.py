"""DOCX -> PDF conversion with swappable backends.

The default backend is headless LibreOffice, which works on both macOS dev
machines and Linux containers without Microsoft Word. A ``docx2pdf`` backend
(Word/AppleScript) is selectable for local dev where Word is available; its
dependency is imported lazily so it stays optional.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "PdfConverter",
    "LibreOfficeConverter",
    "Docx2PdfConverter",
    "ConverterNotAvailableError",
    "get_converter",
    "docx_to_pdf",
]


class ConverterNotAvailableError(RuntimeError):
    """Raised when the selected backend's binary/dependency is missing."""


@runtime_checkable
class PdfConverter(Protocol):
    """Convert a ``.docx`` file to ``.pdf``."""

    def convert(self, docx_path, out_path=None) -> Path:
        ...


class LibreOfficeConverter:
    """Convert DOCX -> PDF via ``soffice --headless --convert-to pdf``."""

    name = "libreoffice"

    def __init__(self, binary: str = "soffice"):
        self._binary = binary

    def _is_available(self) -> bool:
        return shutil.which(self._binary) is not None

    def convert(self, docx_path, out_path=None) -> Path:
        if not self._is_available():
            raise ConverterNotAvailableError(
                f"LibreOffice binary '{self._binary}' not found on PATH. "
                "Install it: macOS `brew install --cask libreoffice`, "
                "Debian/Ubuntu `apt-get install -y libreoffice`."
            )
        src = Path(docx_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"DOCX not found: {src}")

        if out_path is None:
            out_dir = src.parent
            pdf_path = out_dir / (src.stem + ".pdf")
        else:
            pdf_path = Path(out_path)
            out_dir = pdf_path.parent
            out_dir.mkdir(parents=True, exist_ok=True)

        # A per-process profile dir avoids headless profile/lock collisions.
        profile = f"file:///tmp/lo-profile-{os.getpid()}"
        cmd = [
            self._binary,
            "--headless",
            "--norestore",
            f"-env:UserInstallation={profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        produced = out_dir / (src.stem + ".pdf")
        if produced != pdf_path:
            # LibreOffice always writes <stem>.pdf; rename to a custom name.
            shutil.move(str(produced), str(pdf_path))
        return pdf_path


class Docx2PdfConverter:
    """Convert DOCX -> PDF via the optional ``docx2pdf`` package (needs Word)."""

    name = "docx2pdf"

    def convert(self, docx_path, out_path=None) -> Path:
        try:
            from docx2pdf import convert as _convert
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ConverterNotAvailableError(
                "docx2pdf is not installed. Install with `pip install docx2pdf`. "
                "It requires Microsoft Word (macOS/Windows)."
            ) from exc
        src = str(docx_path)
        dest = str(out_path) if out_path is not None else None
        _convert(src, dest)
        if out_path is None:
            return Path(src).with_suffix(".pdf")
        return Path(out_path)


_BACKENDS = {
    "libreoffice": LibreOfficeConverter,
    "docx2pdf": Docx2PdfConverter,
}


def get_converter(backend=None):
    """Return a :class:`PdfConverter` for the requested backend.

    Resolution order: ``backend`` arg -> ``DOCS_PDF_BACKEND`` env ->
    ``libreoffice`` (default). Raises :class:`ValueError` for unknown backends.
    """
    if backend is None:
        backend = os.environ.get("DOCS_PDF_BACKEND", "libreoffice")
    backend = backend.lower()
    if backend not in _BACKENDS:
        raise ValueError(
            f"unknown PDF backend: {backend!r}. "
            f"Supported: {', '.join(sorted(_BACKENDS))}"
        )
    return _BACKENDS[backend]()


def docx_to_pdf(docx_path, *, output_path=None, backend=None) -> Path:
    """Convert ``docx_path`` to PDF and return the PDF path.

    ``output_path`` defaults to the source path with a ``.pdf`` extension.
    ``backend`` selects the converter (see :func:`get_converter`).
    """
    converter = get_converter(backend)
    return converter.convert(docx_path, output_path)
