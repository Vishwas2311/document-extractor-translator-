from collections.abc import Iterable
from typing import Any

from app.schemas.page import (
    BoundingRegion,
    CanonicalDocument,
    PageMetadata,
    Point,
    Span,
    TableCell,
    TableResult,
    TextBlock,
)


def value(
    item: dict[str, Any],
    snake: str,
    camel: str | None = None,
    default: Any = None,
) -> Any:
    if snake in item:
        return item[snake]
    if camel and camel in item:
        return item[camel]
    return default


def spans(item: dict[str, Any]) -> list[Span]:
    return [
        Span(
            offset=int(value(span, "offset", default=0)),
            length=int(value(span, "length", default=0)),
        )
        for span in value(item, "spans", default=[]) or []
    ]


def polygon_points(raw_polygon: Iterable[Any]) -> list[Point]:
    raw = list(raw_polygon or [])
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return [Point(x=float(point["x"]), y=float(point["y"])) for point in raw]
    points: list[Point] = []
    for index in range(0, len(raw) - 1, 2):
        points.append(Point(x=float(raw[index]), y=float(raw[index + 1])))
    return points


def regions(item: dict[str, Any]) -> list[BoundingRegion]:
    output: list[BoundingRegion] = []
    for region in value(item, "bounding_regions", "boundingRegions", []) or []:
        output.append(
            BoundingRegion(
                page_number=int(value(region, "page_number", "pageNumber", 1)),
                polygon=polygon_points(value(region, "polygon", default=[])),
            )
        )
    return output


def slice_utf16(content_utf16: bytes, offset: int, length: int) -> str:
    """Slice text by UTF-16 code-unit offset/length, as Azure Document Intelligence reports spans.

    Document Intelligence span offsets are UTF-16 code-unit offsets, not Python (code-point)
    string indices. Indexing the Python string directly misaligns - and silently corrupts -
    everything after the first character outside the Basic Multilingual Plane (emoji, some
    CJK extensions). `content_utf16` is the document content pre-encoded once as UTF-16LE
    bytes; each UTF-16 code unit is 2 bytes, so offset/length are doubled to get byte bounds.
    """
    start = offset * 2
    end = start + length * 2
    return content_utf16[start:end].decode("utf-16-le")


def overlaps(left: Span, right: Span) -> bool:
    return left.offset < right.offset + right.length and right.offset < left.offset + left.length


def covered_by_table_cells(
    block_spans: list[Span],
    table_cell_spans: list[Span],
    *,
    threshold: float = 0.8,
) -> bool:
    total_length = sum(max(item.length, 0) for item in block_spans)
    if total_length <= 0 or not table_cell_spans:
        return False

    covered_length = 0
    for block_span in block_spans:
        block_start = block_span.offset
        block_end = block_span.offset + block_span.length
        covered_segments: list[tuple[int, int]] = []
        for cell_span in table_cell_spans:
            start = max(block_start, cell_span.offset)
            end = min(block_end, cell_span.offset + cell_span.length)
            if start < end:
                covered_segments.append((start, end))
        if not covered_segments:
            continue
        covered_segments.sort()
        merged_start, merged_end = covered_segments[0]
        for start, end in covered_segments[1:]:
            if start <= merged_end:
                merged_end = max(merged_end, end)
            else:
                covered_length += merged_end - merged_start
                merged_start, merged_end = start, end
        covered_length += merged_end - merged_start

    return covered_length / total_length >= threshold


def language_for(block_spans: list[Span], raw_languages: list[dict[str, Any]]) -> str:
    for language in raw_languages:
        language_spans = spans(language)
        if any(overlaps(a, b) for a in block_spans for b in language_spans):
            return str(value(language, "locale", default="und"))
    return "und"


def confidence_for(block_spans: list[Span], raw_words: list[dict[str, Any]]) -> float | None:
    weighted = 0.0
    total_length = 0
    for word in raw_words:
        word_spans = spans(word)
        if not any(overlaps(a, b) for a in block_spans for b in word_spans):
            continue
        confidence = value(word, "confidence")
        if confidence is None:
            continue
        weight = max(sum(span.length for span in word_spans), 1)
        weighted += float(confidence) * weight
        total_length += weight
    return round(weighted / total_length, 4) if total_length else None


class DocumentIntelligenceMapper:
    def map(self, raw: dict[str, Any], *, document_id: str, filename: str) -> CanonicalDocument:
        content = str(value(raw, "content", default=""))
        content_utf16 = content.encode("utf-16-le")
        raw_pages = value(raw, "pages", default=[]) or []
        page_count = len(raw_pages)
        pages: list[PageMetadata] = []
        raw_words: list[dict[str, Any]] = []
        for page in raw_pages:
            page_spans = spans(page)
            page_text = "".join(
                slice_utf16(content_utf16, item.offset, item.length) for item in page_spans
            )
            if not page_text:
                page_text = "\n".join(
                    str(value(line, "content", default=""))
                    for line in value(page, "lines", default=[]) or []
                )
            pages.append(
                PageMetadata(
                    page_number=int(value(page, "page_number", "pageNumber", len(pages) + 1)),
                    page_count=page_count,
                    width=float(value(page, "width", default=0) or 0),
                    height=float(value(page, "height", default=0) or 0),
                    unit=str(value(page, "unit", default="pixel")),
                    angle=float(value(page, "angle", default=0) or 0),
                    source_text=page_text,
                )
            )
            raw_words.extend(value(page, "words", default=[]) or [])

        raw_languages = value(raw, "languages", default=[]) or []
        raw_tables = value(raw, "tables", default=[]) or []
        table_cell_spans = [
            cell_span
            for table in raw_tables
            for cell in value(table, "cells", default=[]) or []
            for cell_span in spans(cell)
        ]
        blocks: list[TextBlock] = []
        for index, paragraph in enumerate(value(raw, "paragraphs", default=[]) or [], start=1):
            block_spans = spans(paragraph)
            if covered_by_table_cells(block_spans, table_cell_spans):
                continue
            confidence = confidence_for(block_spans, raw_words)
            blocks.append(
                TextBlock(
                    block_id=f"b{index:06d}",
                    reading_order=index,
                    source_text=str(value(paragraph, "content", default="")),
                    source_language=language_for(block_spans, raw_languages),
                    role=value(paragraph, "role"),
                    spans=block_spans,
                    bounding_regions=regions(paragraph),
                    ocr_confidence=confidence,
                    confidence_source="word_length_weighted_mean"
                    if confidence is not None
                    else None,
                )
            )

        tables: list[TableResult] = []
        for index, table in enumerate(raw_tables, start=1):
            cells = [
                TableCell(
                    cell_id=f"t{index:04d}-c{cell_index:04d}",
                    row_index=int(value(cell, "row_index", "rowIndex", 0)),
                    column_index=int(value(cell, "column_index", "columnIndex", 0)),
                    row_span=int(value(cell, "row_span", "rowSpan", 1)),
                    column_span=int(value(cell, "column_span", "columnSpan", 1)),
                    content=str(value(cell, "content", default="")),
                    kind=value(cell, "kind"),
                    spans=spans(cell),
                    bounding_regions=regions(cell),
                )
                for cell_index, cell in enumerate(value(table, "cells", default=[]) or [], start=1)
            ]
            tables.append(
                TableResult(
                    table_id=f"t{index:04d}",
                    row_count=int(value(table, "row_count", "rowCount", 0)),
                    column_count=int(value(table, "column_count", "columnCount", 0)),
                    cells=cells,
                    bounding_regions=regions(table),
                )
            )

        return CanonicalDocument(
            document_id=document_id,
            filename=filename,
            status="normalizing",
            pages=pages,
            blocks=blocks,
            tables=tables,
        )
