from app.schemas.page import (
    BoundingRegion,
    CanonicalDocument,
    PageMetadata,
    Point,
    TableCell,
    TableResult,
    TextBlock,
)
from app.services.table_integrity import TableIntegrityService


def _region(page: int, x0: float, y0: float, x1: float, y1: float) -> BoundingRegion:
    return BoundingRegion(
        page_number=page,
        polygon=[
            Point(x=x0, y=y0),
            Point(x=x1, y=y0),
            Point(x=x1, y=y1),
            Point(x=x0, y=y1),
        ],
    )


def test_aligned_orphan_columns_reconstruct_provider_table_without_mutation() -> None:
    provider_cells = [
        TableCell(
            cell_id=f"provider-{row}-{column}",
            row_index=row,
            column_index=column,
            content=f"provider {row} {column}",
            bounding_regions=[_region(1, 5 + column * 2, 1 + row, 7 + column * 2, 2 + row)],
        )
        for row in range(3)
        for column in range(2)
    ]
    orphan_blocks = [
        TextBlock(
            block_id=f"orphan-{row}-{column}",
            reading_order=row * 2 + column + 1,
            source_text=f"orphan {row} {column}",
            bounding_regions=[_region(1, 1 + column * 2, 1 + row, 2.5 + column * 2, 2 + row)],
        )
        for row in range(3)
        for column in range(2)
    ]
    source = CanonicalDocument(
        document_id="synthetic-table-reconciliation",
        filename="synthetic.pdf",
        status="normalizing",
        pages=[
            PageMetadata(
                page_number=1,
                page_count=1,
                width=10,
                height=10,
                unit="inch",
            )
        ],
        blocks=orphan_blocks,
        tables=[
            TableResult(
                table_id="table-1",
                row_count=3,
                column_count=2,
                cells=provider_cells,
                bounding_regions=[_region(1, 5, 1, 9, 4)],
            )
        ],
    )

    effective, evidence = TableIntegrityService().reconcile(source)

    assert source.tables[0].column_count == 2
    assert len(source.blocks) == 6
    assert evidence.candidate_count == 1
    assert evidence.candidates[0].action == "prepend_columns"
    assert evidence.candidates[0].consumed_block_ids == [
        f"orphan-{row}-{column}"
        for row in range(3)
        for column in range(2)
    ]
    table = effective.tables[0]
    assert (table.provider_row_count, table.provider_column_count) == (3, 2)
    assert (table.row_count, table.column_count) == (3, 4)
    assert table.integrity_status == "reconciled"
    assert len(table.cells) == 12
    assert not effective.blocks
    reconstructed = [cell for cell in table.cells if cell.origin == "reconstructed"]
    assert len(reconstructed) == 6
    assert all(cell.review_required for cell in reconstructed)
    assert all(cell.source_block_ids for cell in reconstructed)


def test_unaligned_blocks_are_not_joined_to_a_provider_table() -> None:
    source = CanonicalDocument(
        document_id="synthetic-no-reconciliation",
        filename="synthetic.pdf",
        status="normalizing",
        pages=[
            PageMetadata(
                page_number=1,
                page_count=1,
                width=10,
                height=10,
                unit="inch",
            )
        ],
        blocks=[
            TextBlock(
                block_id="single-orphan",
                reading_order=1,
                source_text="not a complete column",
                bounding_regions=[_region(1, 1, 1, 4, 2)],
            )
        ],
        tables=[
            TableResult(
                table_id="table-1",
                row_count=2,
                column_count=1,
                cells=[
                    TableCell(
                        cell_id=f"provider-{row}",
                        row_index=row,
                        column_index=0,
                        content="provider",
                        bounding_regions=[_region(1, 5, 1 + row, 9, 2 + row)],
                    )
                    for row in range(2)
                ],
                bounding_regions=[_region(1, 5, 1, 9, 3)],
            )
        ],
    )

    effective, evidence = TableIntegrityService().reconcile(source)

    assert evidence.candidate_count == 0
    assert effective.tables[0].integrity_status == "provider"
    assert effective.tables[0].column_count == 1
    assert [block.block_id for block in effective.blocks] == ["single-orphan"]
