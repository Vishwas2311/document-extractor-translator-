import bisect
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


class _SpanIndex:
    """Interval index for O(log n + k) 'which entries overlap this query span'
    lookups, built once per document/range instead of rescanning the full
    entry list for every text block (O(blocks * entries), which dominates
    mapping time on dense, multi-hundred-page Document Intelligence ranges).

    Entries of the same kind (word spans, table-cell spans) never overlap each
    other in Document Intelligence's own output, which is what makes the fast
    bisect path valid (sorted-by-start also implies sorted-by-end). That
    invariant is verified when the index is built rather than assumed: if it
    ever doesn't hold, queries fall back to an exact linear scan, so results
    are identical to a naive nested-loop scan either way - only speed differs.
    """

    def __init__(self, entries: list[tuple[int, int, Any]]) -> None:
        ordered = sorted(entries, key=lambda entry: entry[0])
        self._entries = ordered
        self._starts = [entry[0] for entry in ordered]
        ends = [entry[1] for entry in ordered]
        self._ends = ends
        self._sane = all(ends[i] <= ends[i + 1] for i in range(len(ends) - 1))

    def __len__(self) -> int:
        return len(self._entries)

    def overlapping(self, query_start: int, query_end: int) -> list[tuple[int, int, Any]]:
        if not self._entries:
            return []
        if not self._sane:
            return [
                entry
                for entry in self._entries
                if entry[0] < query_end and entry[1] > query_start
            ]
        hi = bisect.bisect_left(self._starts, query_end)
        if hi <= 0:
            return []
        lo = bisect.bisect_right(self._ends, query_start)
        return self._entries[lo:hi] if lo < hi else []


def _span_index(spans_by_entry: list[tuple[Any, list[Span]]]) -> _SpanIndex:
    entries = [
        (span.offset, span.offset + span.length, entry_id)
        for entry_id, entry_spans in spans_by_entry
        for span in entry_spans
    ]
    return _SpanIndex(entries)


def covered_by_table_cells(
    block_spans: list[Span],
    cell_index: _SpanIndex,
    *,
    threshold: float = 0.8,
) -> bool:
    total_length = sum(max(item.length, 0) for item in block_spans)
    if total_length <= 0 or len(cell_index) == 0:
        return False

    covered_length = 0
    for block_span in block_spans:
        block_start = block_span.offset
        block_end = block_span.offset + block_span.length
        covered_segments: list[tuple[int, int]] = []
        for cell_start, cell_end, _payload in cell_index.overlapping(block_start, block_end):
            start = max(block_start, cell_start)
            end = min(block_end, cell_end)
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


def language_for(
    block_spans: list[Span],
    language_index: _SpanIndex,
    locales: list[str],
) -> str:
    # Matches must resolve to the first-listed language among all overlaps,
    # mirroring the original "iterate raw_languages in order, return on first
    # match" behavior - not the first spatially found.
    matched_language_ids: set[int] = set()
    for block_span in block_spans:
        for _start, _end, language_id in language_index.overlapping(
            block_span.offset, block_span.offset + block_span.length
        ):
            matched_language_ids.add(language_id)
    if not matched_language_ids:
        return "und"
    return locales[min(matched_language_ids)]


def confidence_for(
    block_spans: list[Span],
    word_index: _SpanIndex,
    word_meta: list[tuple[Any, int]],
) -> float | None:
    matched_word_ids: set[int] = set()
    for block_span in block_spans:
        for _start, _end, word_id in word_index.overlapping(
            block_span.offset, block_span.offset + block_span.length
        ):
            matched_word_ids.add(word_id)

    weighted = 0.0
    total_length = 0
    for word_id in matched_word_ids:
        confidence, weight = word_meta[word_id]
        if confidence is None:
            continue
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
        locales = [str(value(language, "locale", default="und")) for language in raw_languages]
        language_index = _span_index(
            [(lang_id, spans(language)) for lang_id, language in enumerate(raw_languages)]
        )
        raw_tables = value(raw, "tables", default=[]) or []
        table_cell_spans = [
            cell_span
            for table in raw_tables
            for cell in value(table, "cells", default=[]) or []
            for cell_span in spans(cell)
        ]
        table_cell_index = _span_index(
            [(None, [cell_span]) for cell_span in table_cell_spans]
        )

        word_meta: list[tuple[Any, int]] = []
        word_spans_by_id: list[tuple[int, list[Span]]] = []
        for word_id, word in enumerate(raw_words):
            word_spans = spans(word)
            weight = max(sum(span.length for span in word_spans), 1)
            word_meta.append((value(word, "confidence"), weight))
            word_spans_by_id.append((word_id, word_spans))
        word_index = _span_index(word_spans_by_id)

        blocks: list[TextBlock] = []
        for index, paragraph in enumerate(value(raw, "paragraphs", default=[]) or [], start=1):
            block_spans = spans(paragraph)
            if covered_by_table_cells(block_spans, table_cell_index):
                continue
            confidence = confidence_for(block_spans, word_index, word_meta)
            blocks.append(
                TextBlock(
                    block_id=f"b{index:06d}",
                    reading_order=index,
                    source_text=str(value(paragraph, "content", default="")),
                    source_language=language_for(block_spans, language_index, locales),
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
                    source_language=language_for(spans(cell), language_index, locales),
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
