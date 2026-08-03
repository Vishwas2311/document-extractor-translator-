"""Upload hardening: encrypted PDF detection and page-count limits."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import InvalidDocumentError

ENCRYPT_RE = re.compile(rb"/Encrypt(?:\s|/|<<)")
PAGE_RE = re.compile(rb"/Type\s*/Page(?:\s|/|>>)")


def _count_pdf_pages(path: Path, data: bytes) -> int:
    """Prefer pypdf; fall back to a heuristic /Page object count."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if getattr(reader, "is_encrypted", False):
            raise InvalidDocumentError(
                "Password-protected or encrypted PDFs are not accepted. Export an unencrypted copy."
            )
        return len(reader.pages)
    except InvalidDocumentError:
        raise
    except Exception:
        sample = data[: min(len(data), 2_000_000)]
        page_count = len(PAGE_RE.findall(sample))
        if page_count == 0 and len(data) > len(sample):
            page_count = len(PAGE_RE.findall(data))
        return page_count


def assert_pdf_safe(path: Path, *, max_pages: int) -> int | None:
    """Reject encrypted PDFs and enforce a page ceiling.

    Returns an estimated page count for PDFs, or None for non-PDFs.
    """
    if path.suffix.lower() != ".pdf":
        return None

    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise InvalidDocumentError("The file signature is not a valid PDF.")

    # Password/encrypted PDFs must not be sent to Document Intelligence.
    sample = data[: min(len(data), 2_000_000)]
    if ENCRYPT_RE.search(sample):
        raise InvalidDocumentError(
            "Password-protected or encrypted PDFs are not accepted. Export an unencrypted copy."
        )

    page_count = _count_pdf_pages(path, data)
    if page_count > max_pages:
        raise InvalidDocumentError(
            f"Document exceeds the {max_pages}-page limit ({page_count} pages detected)."
        )
    return page_count or None
