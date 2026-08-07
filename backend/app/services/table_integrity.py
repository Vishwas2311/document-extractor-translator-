"""Deterministic repair of provider tables using aligned source OCR blocks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from statistics import fmean
from typing import Literal

from app.schemas.page import (
    BoundingRegion,
    CanonicalDocument,
    Point,
    TableCell,
    TableResult,
    TextBlock,
)
from app.schemas.table_reconciliation import (
    ReconciliationEvidence,
    TableReconciliationCandidate,
    TableReconciliationResult,
)

_MINIMUM_ROWS = 2
_MAXIMUM_ADDED_COLUMNS = 4
_MINIMUM_VERTICAL_OVERLAP = 0.55
_MAXIMUM_COLUMN_START_SPREAD_RATIO = 0.04
_MAXIMUM_SIDE_EXTENT_RATIO = 1.35
_POLICY: dict[str, str | int | float] = {
    "algorithm": "aligned-orphan-columns-1.0",
    "minimum_rows": _MINIMUM_ROWS,
    "maximum_added_columns": _MAXIMUM_ADDED_COLUMNS,
    "minimum_vertical_overlap": _MINIMUM_VERTICAL_OVERLAP,
    "maximum_column_start_spread_ratio": _MAXIMUM_COLUMN_START_SPREAD_RATIO,
    "maximum_side_extent_ratio": _MAXIMUM_SIDE_EXTENT_RATIO,
}


@dataclass(frozen=True)
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


def _region_box(region: BoundingRegion) -> _Box | None:
    if not region.polygon:
        return None
    xs = [point.x for point in region.polygon]
    ys = [point.y for point in region.polygon]
    return _Box(min(xs), min(ys), max(xs), max(ys))


def _page_box(regions: list[BoundingRegion], page_number: int) -> _Box | None:
    boxes = [
        box
        for region in regions
        if region.page_number == page_number
        if (box := _region_box(region)) is not None
    ]
    if not boxes:
        return None
    return _Box(
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    )


def _vertical_overlap(left: _Box, right: _Box) -> float:
    intersection = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    denominator = min(left.height, right.height)
    return intersection / denominator if denominator else 0.0


class TableIntegrityService:
    """Build a derived effective layout while keeping provider extraction immutable."""

    @property
    def policy_fingerprint(self) -> str:
        payload = json.dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def reconcile(
        self, document: CanonicalDocument
    ) -> tuple[CanonicalDocument, TableReconciliationResult]:
        effective = document.model_copy(deep=True)
        page_widths = {page.page_number: page.width for page in effective.pages}
        consumed: set[str] = set()
        candidates: list[TableReconciliationCandidate] = []

        for table in effective.tables:
            match = self._candidate_for_table(
                table,
                effective.blocks,
                page_widths=page_widths,
                excluded_block_ids=consumed,
            )
            if match is None:
                continue
            candidate, row_blocks = match
            self._apply_candidate(table, candidate, row_blocks)
            consumed.update(candidate.consumed_block_ids)
            candidates.append(candidate)

        if consumed:
            effective.blocks = [
                block for block in effective.blocks if block.block_id not in consumed
            ]
            effective.schema_version = "1.1"

        result = TableReconciliationResult(
            document_id=document.document_id,
            algorithm_fingerprint=self.policy_fingerprint,
            candidate_count=len(candidates),
            candidates=candidates,
        )
        return effective, result

    def _candidate_for_table(
        self,
        table: TableResult,
        blocks: list[TextBlock],
        *,
        page_widths: dict[int, float],
        excluded_block_ids: set[str],
    ) -> tuple[TableReconciliationCandidate, dict[int, list[TextBlock]]] | None:
        if table.row_count < _MINIMUM_ROWS or not table.cells:
            return None
        pages = {
            region.page_number
            for cell in table.cells
            for region in cell.bounding_regions
        } | {region.page_number for region in table.bounding_regions}
        if len(pages) != 1:
            return None
        page_number = next(iter(pages))
        table_box = _page_box(table.bounding_regions, page_number) or _page_box(
            [region for cell in table.cells for region in cell.bounding_regions], page_number
        )
        if table_box is None or table_box.width <= 0:
            return None

        row_boxes: dict[int, _Box] = {}
        for row_index in range(table.row_count):
            row_box = _page_box(
                [
                    region
                    for cell in table.cells
                    if cell.row_index == row_index
                    for region in cell.bounding_regions
                ],
                page_number,
            )
            if row_box is None:
                return None
            row_boxes[row_index] = row_box

        eligible = [
            block
            for block in blocks
            if block.block_id not in excluded_block_ids
            and block.role
            not in {"title", "sectionHeading", "pageHeader", "pageFooter", "pageNumber"}
            and any(region.page_number == page_number for region in block.bounding_regions)
            and block.source_text.strip()
        ]
        for side in ("left", "right"):
            row_blocks = self._aligned_side_blocks(
                eligible,
                row_boxes=row_boxes,
                table_box=table_box,
                page_number=page_number,
                page_width=page_widths.get(page_number, table_box.x1),
                side=side,
            )
            if row_blocks is None:
                continue
            added_columns = len(next(iter(row_blocks.values())))
            block_ids = [
                block.block_id
                for row_index in sorted(row_blocks)
                for block in row_blocks[row_index]
            ]
            digest = hashlib.sha256(
                f"{table.table_id}:{side}:{','.join(block_ids)}".encode()
            ).hexdigest()[:16]
            confidence = 0.95 if table.row_count >= 3 else 0.9
            candidate = TableReconciliationCandidate(
                candidate_id=f"trc-{digest}",
                table_id=table.table_id,
                page_number=page_number,
                action="prepend_columns" if side == "left" else "append_columns",
                provider_row_count=table.row_count,
                provider_column_count=table.column_count,
                proposed_row_count=table.row_count,
                proposed_column_count=table.column_count + added_columns,
                added_cell_count=len(block_ids),
                consumed_block_ids=block_ids,
                confidence=confidence,
                evidence=[
                    ReconciliationEvidence(
                        code="all_provider_rows_have_aligned_orphan_blocks",
                        score=confidence,
                        detail="Every provider row has the same number of aligned source blocks.",
                    ),
                    ReconciliationEvidence(
                        code="stable_orphan_column_alignment",
                        score=confidence,
                        detail=(
                            "Aligned source blocks form stable columns beside the provider table."
                        ),
                    ),
                ],
            )
            return candidate, row_blocks
        return None

    @staticmethod
    def _aligned_side_blocks(
        blocks: list[TextBlock],
        *,
        row_boxes: dict[int, _Box],
        table_box: _Box,
        page_number: int,
        page_width: float,
        side: Literal["left", "right"],
    ) -> dict[int, list[TextBlock]] | None:
        grouped: dict[int, list[tuple[_Box, TextBlock]]] = {}
        maximum_extent = table_box.width * _MAXIMUM_SIDE_EXTENT_RATIO
        tolerance = max(page_width * 0.01, 0.05)
        for block in blocks:
            block_box = _page_box(block.bounding_regions, page_number)
            if block_box is None:
                continue
            if side == "left":
                beside = (
                    block_box.x0 < table_box.x0
                    and block_box.x1 <= table_box.x0 + tolerance
                    and block_box.x1 >= table_box.x0 - maximum_extent
                )
            else:
                beside = (
                    block_box.x1 > table_box.x1
                    and block_box.x0 >= table_box.x1 - tolerance
                    and block_box.x0 <= table_box.x1 + maximum_extent
                )
            if not beside:
                continue
            matching_rows = [
                row_index
                for row_index, row_box in row_boxes.items()
                if _vertical_overlap(block_box, row_box) >= _MINIMUM_VERTICAL_OVERLAP
            ]
            if len(matching_rows) == 1:
                grouped.setdefault(matching_rows[0], []).append((block_box, block))

        if set(grouped) != set(row_boxes):
            return None
        counts = {len(items) for items in grouped.values()}
        if len(counts) != 1:
            return None
        column_count = next(iter(counts))
        if not 1 <= column_count <= _MAXIMUM_ADDED_COLUMNS:
            return None

        ordered: dict[int, list[TextBlock]] = {}
        starts_by_column: list[list[float]] = [[] for _ in range(column_count)]
        for row_index, items in grouped.items():
            sorted_items = sorted(items, key=lambda item: item[0].x0)
            ordered[row_index] = [item[1] for item in sorted_items]
            for column_index, (box, _) in enumerate(sorted_items):
                starts_by_column[column_index].append(box.x0)
        maximum_spread = max(page_width * _MAXIMUM_COLUMN_START_SPREAD_RATIO, 0.2)
        if any(max(values) - min(values) > maximum_spread for values in starts_by_column):
            return None

        centers = [fmean(values) for values in starts_by_column]
        if any(right - left < tolerance for left, right in zip(centers, centers[1:], strict=False)):
            return None
        return ordered

    @staticmethod
    def _apply_candidate(
        table: TableResult,
        candidate: TableReconciliationCandidate,
        row_blocks: dict[int, list[TextBlock]],
    ) -> None:
        added_columns = candidate.proposed_column_count - candidate.provider_column_count
        if candidate.action == "prepend_columns":
            for cell in table.cells:
                cell.column_index += added_columns
        new_cells: list[TableCell] = []
        for row_index in sorted(row_blocks):
            for ordinal, block in enumerate(row_blocks[row_index]):
                column_index = (
                    ordinal
                    if candidate.action == "prepend_columns"
                    else candidate.provider_column_count + ordinal
                )
                digest = hashlib.sha256(
                    f"{candidate.candidate_id}:{block.block_id}:{row_index}:{column_index}".encode()
                ).hexdigest()[:12]
                new_cells.append(
                    TableCell(
                        cell_id=f"{table.table_id}-r{digest}",
                        row_index=row_index,
                        column_index=column_index,
                        content=block.source_text,
                        source_language=block.source_language,
                        translated_content=block.translated_text,
                        translation_status=block.translation_status,
                        review_required=True,
                        warnings=[
                            "Cell reconstructed from an aligned source OCR block; "
                            "reviewer acceptance is required."
                        ],
                        spans=block.spans,
                        bounding_regions=block.bounding_regions,
                        origin="reconstructed",
                        source_block_ids=[block.block_id],
                        reconciliation_candidate_id=candidate.candidate_id,
                    )
                )
        table.cells.extend(new_cells)
        table.cells.sort(key=lambda cell: (cell.row_index, cell.column_index, cell.cell_id))
        table.provider_row_count = candidate.provider_row_count
        table.provider_column_count = candidate.provider_column_count
        table.row_count = candidate.proposed_row_count
        table.column_count = candidate.proposed_column_count
        table.integrity_status = "reconciled"
        table.reconciliation_candidate_id = candidate.candidate_id
        boxes = [
            box
            for cell in table.cells
            for region in cell.bounding_regions
            if region.page_number == candidate.page_number
            if (box := _region_box(region)) is not None
        ]
        if boxes:
            table.bounding_regions = [
                BoundingRegion(
                    page_number=candidate.page_number,
                    polygon=[
                        Point(x=min(box.x0 for box in boxes), y=min(box.y0 for box in boxes)),
                        Point(x=max(box.x1 for box in boxes), y=min(box.y0 for box in boxes)),
                        Point(x=max(box.x1 for box in boxes), y=max(box.y1 for box in boxes)),
                        Point(x=min(box.x0 for box in boxes), y=max(box.y1 for box in boxes)),
                    ],
                )
            ]
