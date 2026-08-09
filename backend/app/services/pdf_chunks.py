"""Derive temporary PDF page chunks for faster Document Intelligence calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast


def chunk_pdf_path(document_dir: Path, start: int, end: int) -> Path:
    """Return a deterministic path for a derived page chunk (never the original)."""
    chunk_dir = document_dir / "processing" / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    return chunk_dir / f"pages-{start:04d}-{end:04d}.pdf"


def write_pdf_page_chunk(source_path: Path, destination: Path, start: int, end: int) -> Path:
    """Write an immutable-derived PDF containing original pages [start, end] (1-based).

    The original source PDF is never modified. Page order and rotation are preserved
    by copying page objects through pypdf.
    """
    if start < 1 or end < start:
        raise ValueError(f"Invalid page chunk bounds: {start}-{end}")
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(source_path))
    if getattr(reader, "is_encrypted", False):
        raise ValueError("Encrypted PDFs cannot be chunked.")
    total = len(reader.pages)
    if end > total:
        raise ValueError(f"Chunk end {end} exceeds PDF page count {total}.")

    writer = PdfWriter()
    for index in range(start - 1, end):
        writer.add_page(reader.pages[index])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as handle:
        writer.write(handle)
    temporary.replace(destination)
    return destination


def remap_di_page_numbers(payload: dict[str, Any], *, page_offset: int) -> dict[str, Any]:
    """Shift DI pageNumber fields so chunk-local pages map back to original pages.

    A chunk covering original pages 51-100 returns DI pages 1-50. With
    ``page_offset=50`` those become 51-100.
    """
    if page_offset == 0:
        return payload

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            updated = {
                key: walk(value)
                for key, value in node.items()
                if key not in {"pageNumber", "page_number"}
            }
            if "pageNumber" in node:
                updated["pageNumber"] = int(node["pageNumber"]) + page_offset
            if "page_number" in node:
                updated["page_number"] = int(node["page_number"]) + page_offset
            return updated
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    # `walk` recurses through arbitrarily-nested Any (dict/list/scalar); this call's
    # input is a dict and the dict branch always returns a dict, so the result is safe
    # to narrow back to the function's declared return type.
    return cast(dict[str, Any], walk(payload))
