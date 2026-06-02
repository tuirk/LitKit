"""Light-weight PDF text extraction.

Tries pypdf, then pdfminer.six, then falls back to None. The full-text
screening script handles the None case by writing the PDF path into
the batch JSONL and letting the agent open it directly.

We intentionally do NOT depend on poppler/pdftotext to keep the engine
pure-Python. If the user installs pypdf or pdfminer.six, extraction is
automatic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def extract_text(pdf_path: Path, max_chars: int = 30000) -> Optional[str]:
    """Extract plain text from a PDF. Returns None if no extractor available
    or extraction fails. Truncates at max_chars to keep batches readable."""
    text = _try_pypdf(pdf_path)
    if text is None:
        text = _try_pdfminer(pdf_path)
    if text is None:
        return None
    text = " ".join(text.split())  # collapse whitespace
    if len(text) > max_chars:
        # Keep the abstract/intro AND a tail with conclusions/methods
        head = text[: max_chars - 5000]
        tail = text[-5000:]
        text = f"{head}\n\n[...truncated...]\n\n{tail}"
    return text


def _try_pypdf(pdf_path: Path) -> Optional[str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None


def _try_pdfminer(pdf_path: Path) -> Optional[str]:
    try:
        from pdfminer.high_level import extract_text as _extract  # type: ignore
    except ImportError:
        return None
    try:
        return _extract(str(pdf_path))
    except Exception:
        return None
