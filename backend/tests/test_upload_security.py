"""Upload page-limit and PDF safety checks for 300-page support."""

from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.core.exceptions import InvalidDocumentError
from app.services.upload_security import assert_pdf_safe


def _make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def test_assert_pdf_safe_accepts_300_pages(tmp_path: Path) -> None:
    path = tmp_path / "ok.pdf"
    _make_pdf(path, 300)
    assert assert_pdf_safe(path, max_pages=300) == 300


def test_assert_pdf_safe_rejects_301_pages(tmp_path: Path) -> None:
    path = tmp_path / "too-big.pdf"
    _make_pdf(path, 301)
    with pytest.raises(InvalidDocumentError, match="301"):
        assert_pdf_safe(path, max_pages=300)


def test_assert_pdf_safe_rejects_zero_pages(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    _make_pdf(path, 0)
    with pytest.raises(InvalidDocumentError, match="no readable pages"):
        assert_pdf_safe(path, max_pages=300)


def test_assert_pdf_safe_rejects_a_real_password_protected_pdf(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password="synthetic-password")
    with path.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(InvalidDocumentError, match="[Ee]ncrypted"):
        assert_pdf_safe(path, max_pages=300)


def test_assert_pdf_safe_rejects_corrupted_garbage_bytes(tmp_path: Path) -> None:
    path = tmp_path / "corrupted.pdf"
    path.write_bytes(b"this is not a PDF at all, just garbage bytes\x00\x01\x02")

    with pytest.raises(InvalidDocumentError, match="not a valid PDF"):
        assert_pdf_safe(path, max_pages=300)


def test_assert_pdf_safe_does_not_reject_an_unparseable_pdf_the_heuristic_undercounts(
    tmp_path: Path,
) -> None:
    """A real %PDF- file that pypdf fails to parse (e.g. a producer using compressed
    object/xref streams pypdf can't handle) and whose bytes happen to contain no
    literal `/Type /Page` marker must NOT be rejected as "no readable pages" - the
    heuristic fallback undercounting to 0 means "couldn't confirm," not "confirmed
    empty." It should fall through to an unknown (None) page count instead."""
    path = tmp_path / "unparseable-but-not-empty.pdf"
    # Valid signature, but no xref/trailer pypdf can follow, and no literal
    # "/Type /Page" bytes anywhere - forces the untrusted heuristic-fallback path.
    path.write_bytes(b"%PDF-1.7\n" + (b"\x00\x01\x02not-a-real-object-stream" * 50))

    assert assert_pdf_safe(path, max_pages=300) is None
