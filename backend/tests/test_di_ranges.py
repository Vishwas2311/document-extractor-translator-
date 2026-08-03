from app.schemas.page import (
    BoundingRegion,
    CanonicalDocument,
    PageMetadata,
    Point,
    TextBlock,
)
from app.services.di_ranges import (
    assign_stable_ids,
    format_pages_param,
    merge_canonical_parts,
    page_ranges,
    range_artifact_path,
)


def test_page_ranges_split_evenly() -> None:
    assert list(page_ranges(100, 25)) == [(1, 25), (26, 50), (51, 75), (76, 100)]
    assert list(page_ranges(10, 25)) == [(1, 10)]
    assert list(page_ranges(26, 25)) == [(1, 25), (26, 26)]


def test_format_pages_param() -> None:
    assert format_pages_param(1, 25) == "1-25"
    assert format_pages_param(7, 7) == "7"


def test_range_artifact_path_is_span_keyed() -> None:
    assert range_artifact_path(1, 25) == "raw/ranges/range-0001-0025.json"
    assert range_artifact_path(26, 50) == "raw/ranges/range-0026-0050.json"


def _part(document_id: str, page_number: int, text: str) -> CanonicalDocument:
    return CanonicalDocument(
        document_id=document_id,
        filename="doc.pdf",
        status="normalizing",
        pages=[
            PageMetadata(
                page_number=page_number,
                page_count=1,
                width=8.5,
                height=11,
                unit="inch",
                source_text=text,
            )
        ],
        blocks=[
            TextBlock(
                block_id="b000001",
                reading_order=1,
                source_text=text,
                bounding_regions=[
                    BoundingRegion(
                        page_number=page_number,
                        polygon=[
                            Point(x=1, y=1),
                            Point(x=2, y=1),
                            Point(x=2, y=2),
                            Point(x=1, y=2),
                        ],
                    )
                ],
            )
        ],
    )


def test_merge_canonical_parts_uses_stable_page_ids() -> None:
    merged = merge_canonical_parts(
        [_part("doc-1", 1, "اول"), _part("doc-1", 26, "第二")],
        document_id="doc-1",
        filename="doc.pdf",
    )
    assert [page.page_number for page in merged.pages] == [1, 26]
    assert all(page.page_count == 26 for page in merged.pages)
    assert [block.block_id for block in merged.blocks] == ["p0001-b0001", "p0026-b0001"]
    assert merged.blocks[0].source_text == "اول"
    assert merged.blocks[1].source_text == "第二"


def test_assign_stable_ids_matches_merge() -> None:
    progressive = assign_stable_ids(_part("doc-1", 26, "第二"))
    merged = merge_canonical_parts(
        [_part("doc-1", 1, "اول"), _part("doc-1", 26, "第二")],
        document_id="doc-1",
        filename="doc.pdf",
    )
    assert progressive.blocks[0].block_id == "p0026-b0001"
    assert merged.blocks[1].block_id == progressive.blocks[0].block_id
