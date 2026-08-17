"""Page-range Document Intelligence helpers for large multipage PDFs."""

from __future__ import annotations

from collections.abc import Iterator

from app.core.exceptions import AzureServiceError
from app.schemas.page import CanonicalDocument, PageMetadata, TableResult, TextBlock


def page_ranges(total_pages: int, range_size: int) -> Iterator[tuple[int, int]]:
    """Yield inclusive 1-based (start, end) page ranges."""
    if total_pages < 1:
        return
    size = max(1, range_size)
    start = 1
    while start <= total_pages:
        end = min(start + size - 1, total_pages)
        yield start, end
        start = end + 1


def format_pages_param(start: int, end: int) -> str:
    return f"{start}-{end}" if start != end else str(start)


def range_artifact_path(start: int, end: int) -> str:
    """Span-keyed path so resume stays valid if DI_PAGE_RANGE_SIZE changes."""
    return f"raw/ranges/range-{start:04d}-{end:04d}.json"


def legacy_range_artifact_path(index: int) -> str:
    """Pre-span-key artifact naming (range index only)."""
    return f"raw/ranges/range-{index:04d}.json"


def assign_stable_ids(document: CanonicalDocument) -> CanonicalDocument:
    """Assign page-stable block/table IDs so progressive and final artifacts match."""
    blocks_by_page: dict[int, list[TextBlock]] = {}
    for block in document.blocks:
        page = block.bounding_regions[0].page_number if block.bounding_regions else 0
        blocks_by_page.setdefault(page, []).append(block)

    renumbered_blocks: list[TextBlock] = []
    global_order = 0
    for page in sorted(blocks_by_page):
        page_blocks = sorted(blocks_by_page[page], key=_block_sort_key)
        for order_on_page, block in enumerate(page_blocks, start=1):
            global_order += 1
            copied = block.model_copy(deep=True)
            copied.block_id = f"p{page:04d}-b{order_on_page:04d}"
            copied.reading_order = global_order
            renumbered_blocks.append(copied)

    tables_by_page: dict[int, list[TableResult]] = {}
    for table in document.tables:
        page = table.bounding_regions[0].page_number if table.bounding_regions else 0
        tables_by_page.setdefault(page, []).append(table)

    renumbered_tables: list[TableResult] = []
    for page in sorted(tables_by_page):
        for table_index, table in enumerate(tables_by_page[page], start=1):
            copied_table = table.model_copy(deep=True)
            copied_table.table_id = f"p{page:04d}-t{table_index:04d}"
            for cell_index, cell in enumerate(copied_table.cells, start=1):
                cell.cell_id = f"{copied_table.table_id}-c{cell_index:04d}"
            renumbered_tables.append(copied_table)

    return document.model_copy(
        update={"blocks": renumbered_blocks, "tables": renumbered_tables}
    )


def merge_canonical_parts(
    parts: list[CanonicalDocument],
    *,
    document_id: str,
    filename: str,
) -> CanonicalDocument:
    """Merge per-range mapped documents into one canonical document.

    Reassigns block/table IDs with page-stable identifiers so progressive
    page JSON and the final normalized document stay aligned.
    """
    pages: list[PageMetadata] = []
    blocks: list[TextBlock] = []
    tables: list[TableResult] = []
    seen_pages: set[int] = set()

    for part in parts:
        for page in part.pages:
            if page.page_number in seen_pages:
                # Ranges are disjoint by construction. A duplicate page across
                # parts would silently duplicate its blocks/tables (they are
                # extended wholesale below), so fail loudly instead of merging
                # corrupted output.
                raise AzureServiceError(
                    "Document Intelligence returned overlapping analysis ranges: "
                    f"page {page.page_number} appeared in more than one range.",
                    retryable=False,
                )
            seen_pages.add(page.page_number)
            pages.append(page)
        blocks.extend(part.blocks)
        tables.extend(part.tables)

    pages.sort(key=lambda item: item.page_number)
    page_count = max((page.page_number for page in pages), default=max(seen_pages, default=0))
    for page in pages:
        page.page_count = page_count

    merged = CanonicalDocument(
        document_id=document_id,
        filename=filename,
        status="normalizing",
        pages=pages,
        blocks=blocks,
        tables=tables,
    )
    return assign_stable_ids(merged)


def _block_sort_key(block: TextBlock) -> tuple[int, int, int]:
    page = block.bounding_regions[0].page_number if block.bounding_regions else 0
    return (page, block.reading_order, block.spans[0].offset if block.spans else 0)
