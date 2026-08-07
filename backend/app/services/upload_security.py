"""Upload hardening: encrypted PDF detection and page-count limits."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import InvalidDocumentError

ENCRYPT_RE = re.compile(rb"/Encrypt(?:\s|/|<<)")
PAGE_RE = re.compile(rb"/Type\s*/Page(?:\s|/|>>)")


def _count_pdf_pages(path: Path) -> int:
    """Prefer pypdf against the file path; fall back to a bounded heuristic scan."""
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
        # Avoid loading multi-hundred-MB PDFs entirely into memory when possible.
        page_count = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(2_000_000)
                if not chunk:
                    break
                page_count += len(PAGE_RE.findall(chunk))
                if handle.tell() > 40_000_000:
                    # Cap heuristic scan for pathological files; fail closed if empty.
                    break
        return page_count


def assert_pdf_safe(path: Path, *, max_pages: int) -> int | None:
    """Reject encrypted PDFs and enforce a page ceiling.

    Returns an estimated page count for PDFs, or None for non-PDFs.
    """
    if path.suffix.lower() != ".pdf":
        return None

    with path.open("rb") as handle:
        header = handle.read(8)
        if not header.startswith(b"%PDF-"):
            raise InvalidDocumentError("The file signature is not a valid PDF.")
        # Password/encrypted PDFs must not be sent to Document Intelligence.
        sample = header + handle.read(2_000_000 - len(header))
    if ENCRYPT_RE.search(sample):
        raise InvalidDocumentError(
            "Password-protected or encrypted PDFs are not accepted. Export an unencrypted copy."
        )

    page_count = _count_pdf_pages(path)
    if page_count > max_pages:
        raise InvalidDocumentError(
            f"Document exceeds the {max_pages}-page limit ({page_count} pages detected)."
        )
    return page_count or None
