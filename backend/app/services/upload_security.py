"""Upload hardening: encrypted PDF detection and page-count limits."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import InvalidDocumentError

ENCRYPT_RE = re.compile(rb"/Encrypt(?:\s|/|<<)")
PAGE_RE = re.compile(rb"/Type\s*/Page(?:\s|/|>>)")


def _count_pdf_pages(path: Path) -> tuple[int, bool]:
    """Prefer pypdf against the file path; fall back to a bounded heuristic scan.

    Returns `(page_count, trusted)`. `trusted` is True only when pypdf itself
    successfully parsed the file - the regex fallback scans for literal `/Type /Page`
    bytes and misses pages stored inside compressed object/cross-reference streams
    (common in PDFs from many producers), so a 0 from the fallback means "the
    heuristic didn't find any," not "this document has no pages."
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if getattr(reader, "is_encrypted", False):
            raise InvalidDocumentError(
                "Password-protected or encrypted PDFs are not accepted. Export an unencrypted copy."
            )
        return len(reader.pages), True
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
        return page_count, False


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

    page_count, trusted = _count_pdf_pages(path)
    if page_count > max_pages:
        raise InvalidDocumentError(
            f"Document exceeds the {max_pages}-page limit ({page_count} pages detected)."
        )
    if page_count == 0 and trusted:
        # Only reject on a *trusted* zero (pypdf itself parsed the file and confirmed
        # no pages). An untrusted zero from the heuristic fallback means "we couldn't
        # confirm," not "there are none" - falls through to `page_count or None` below,
        # same as the pre-existing "unknown page count" behavior.
        raise InvalidDocumentError("The PDF has no readable pages.")
    return page_count or None
