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
