from app.integrations.document_intelligence.mapper import (
    DocumentIntelligenceMapper,
    slice_utf16,
)


def test_maps_layout_response_to_page_aware_canonical_document() -> None:
    content = "مرحبا\n青年支持"
    raw = {
        "content": content,
        "pages": [
            {
                "pageNumber": 1,
                "width": 8.5,
                "height": 11,
                "unit": "inch",
                "spans": [{"offset": 0, "length": len(content)}],
                "words": [
                    {"spans": [{"offset": 0, "length": 5}], "confidence": 0.98},
                    {"spans": [{"offset": 6, "length": 4}], "confidence": 0.94},
                ],
            }
        ],
        "paragraphs": [
            {
                "content": "مرحبا",
                "spans": [{"offset": 0, "length": 5}],
                "boundingRegions": [{"pageNumber": 1, "polygon": [1, 1, 4, 1, 4, 2, 1, 2]}],
            },
            {
                "content": "青年支持",
                "spans": [{"offset": 6, "length": 4}],
                "boundingRegions": [{"pageNumber": 1, "polygon": [1, 3, 4, 3, 4, 4, 1, 4]}],
            },
        ],
        "languages": [
            {"locale": "ar", "spans": [{"offset": 0, "length": 5}]},
            {"locale": "zh-Hans", "spans": [{"offset": 6, "length": 4}]},
        ],
    }

    result = DocumentIntelligenceMapper().map(raw, document_id="doc-1", filename="intake.pdf")

    assert result.document_id == "doc-1"
    assert result.pages[0].page_number == 1
    assert result.pages[0].source_text == content
    assert [block.source_language for block in result.blocks] == ["ar", "zh-Hans"]
    assert result.blocks[0].ocr_confidence == 0.98
    assert result.blocks[1].bounding_regions[0].polygon[2].x == 4


def test_page_text_uses_utf16_code_unit_offsets_for_non_bmp_content() -> None:
    # "\U0001F600" is one Python character but a two-code-unit UTF-16 surrogate pair.
    # Azure Document Intelligence span offsets are UTF-16 code-unit offsets, so a naive
    # Python string slice misaligns for every span after a non-BMP character.
    content = "\U0001F600nameTAIL"

    # Sanity check the fixture actually exercises the misalignment this test targets.
    assert content[2:6] != "name"

    raw = {
        "content": content,
        "pages": [
            {
                "pageNumber": 1,
                "width": 8.5,
                "height": 11,
                "unit": "inch",
                # UTF-16 code units 2-5 ("name") - the emoji occupies units 0-1.
                "spans": [{"offset": 2, "length": 4}],
            }
        ],
    }

    result = DocumentIntelligenceMapper().map(raw, document_id="doc-emoji", filename="intake.pdf")

    assert result.pages[0].source_text == "name"


def test_slice_utf16_matches_ascii_python_slicing() -> None:
    content_utf16 = "hello world".encode("utf-16-le")
    assert slice_utf16(content_utf16, 6, 5) == "world"


def test_table_cell_paragraphs_are_not_duplicated_as_text_blocks() -> None:
    content = "Title\nField\nValue"
    raw = {
        "content": content,
        "pages": [
            {
                "pageNumber": 1,
                "width": 8.5,
                "height": 11,
                "unit": "inch",
                "spans": [{"offset": 0, "length": len(content)}],
            }
        ],
        "paragraphs": [
            {
                "content": "Title",
                "spans": [{"offset": 0, "length": 5}],
                "boundingRegions": [
                    {"pageNumber": 1, "polygon": [1, 1, 4, 1, 4, 1.5, 1, 1.5]}
                ],
            },
            {
                "content": "Field",
                "spans": [{"offset": 6, "length": 5}],
                "boundingRegions": [
                    {"pageNumber": 1, "polygon": [1, 2, 3, 2, 3, 2.5, 1, 2.5]}
                ],
            },
            {
                "content": "Value",
                "spans": [{"offset": 12, "length": 5}],
                "boundingRegions": [
                    {"pageNumber": 1, "polygon": [3, 2, 5, 2, 5, 2.5, 3, 2.5]}
                ],
            },
        ],
        "tables": [
            {
                "rowCount": 1,
                "columnCount": 2,
                "boundingRegions": [
                    {"pageNumber": 1, "polygon": [1, 2, 5, 2, 5, 2.5, 1, 2.5]}
                ],
                "cells": [
                    {
                        "rowIndex": 0,
                        "columnIndex": 0,
                        "content": "Field",
                        "spans": [{"offset": 6, "length": 5}],
                        "boundingRegions": [
                            {"pageNumber": 1, "polygon": [1, 2, 3, 2, 3, 2.5, 1, 2.5]}
                        ],
                    },
                    {
                        "rowIndex": 0,
                        "columnIndex": 1,
                        "content": "Value",
                        "spans": [{"offset": 12, "length": 5}],
                        "boundingRegions": [
                            {"pageNumber": 1, "polygon": [3, 2, 5, 2, 5, 2.5, 3, 2.5]}
                        ],
                    },
                ],
            }
        ],
    }

    result = DocumentIntelligenceMapper().map(raw, document_id="doc-table", filename="table.pdf")

    assert [block.source_text for block in result.blocks] == ["Title"]
    assert [cell.content for cell in result.tables[0].cells] == ["Field", "Value"]
    assert result.tables[0].cells[0].spans[0].offset == 6