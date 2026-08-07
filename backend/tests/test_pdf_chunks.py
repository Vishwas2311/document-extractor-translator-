"""Tests for PDF chunking and DI page remapping used by large-document extraction."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.services.pdf_chunks import (
    chunk_pdf_path,
    remap_di_page_numbers,
    write_pdf_page_chunk,
)


def _make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def test_write_pdf_page_chunk_preserves_original_page_subset(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _make_pdf(source, 5)
    destination = chunk_pdf_path(tmp_path / "doc", 2, 4)
    write_pdf_page_chunk(source, destination, 2, 4)

    assert destination.exists()
    assert len(PdfReader(str(source)).pages) == 5
    assert len(PdfReader(str(destination)).pages) == 3


def test_remap_di_page_numbers_shifts_nested_page_fields() -> None:
    payload = {
        "pages": [{"pageNumber": 1}, {"pageNumber": 2}],
        "tables": [
            {
                "boundingRegions": [{"pageNumber": 1}],
                "cells": [{"boundingRegions": [{"page_number": 2}]}],
            }
        ],
    }

    remapped = remap_di_page_numbers(payload, page_offset=50)

    assert remapped["pages"][0]["pageNumber"] == 51
    assert remapped["pages"][1]["pageNumber"] == 52
    assert remapped["tables"][0]["boundingRegions"][0]["pageNumber"] == 51
    assert remapped["tables"][0]["cells"][0]["boundingRegions"][0]["page_number"] == 52
