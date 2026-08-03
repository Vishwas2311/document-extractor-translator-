from collections import defaultdict

from app.schemas.page import CanonicalDocument, PageResult, TableResult, TextBlock


class ExportService:
    def page_results(
        self,
        document: CanonicalDocument,
        final_status: str,
        *,
        only_pages: set[int] | None = None,
    ) -> list[PageResult]:
        blocks_by_page: dict[int, list[TextBlock]] = defaultdict(list)
        for block in document.blocks:
            pages = {
                region.page_number
                for region in block.bounding_regions
                if only_pages is None or region.page_number in only_pages
            }
            for page_number in pages:
                page_regions = [
                    region
                    for region in block.bounding_regions
                    if region.page_number == page_number
                ]
                if page_regions:
                    blocks_by_page[page_number].append(
                        block.model_copy(update={"bounding_regions": page_regions})
                    )

        tables_by_page: dict[int, list[TableResult]] = defaultdict(list)
        for table in document.tables:
            candidate_pages = {
                region.page_number for region in table.bounding_regions
            } | {
                region.page_number
                for cell in table.cells
                for region in cell.bounding_regions
            }
            if only_pages is not None:
                candidate_pages &= only_pages
            for page_number in candidate_pages:
                table_regions = [
                    region
                    for region in table.bounding_regions
                    if region.page_number == page_number
                ]
                page_cells = []
                for cell in table.cells:
                    cell_regions = [
                        region
                        for region in cell.bounding_regions
                        if region.page_number == page_number
                    ]
                    if cell_regions:
                        page_cells.append(
                            cell.model_copy(update={"bounding_regions": cell_regions})
                        )
                if table_regions or page_cells:
                    tables_by_page[page_number].append(
                        table.model_copy(
                            update={"bounding_regions": table_regions, "cells": page_cells}
                        )
                    )

        results: list[PageResult] = []
        for page in document.pages:
            if only_pages is not None and page.page_number not in only_pages:
                continue
            page_blocks = blocks_by_page.get(page.page_number, [])
            page_tables = tables_by_page.get(page.page_number, [])
            translated_parts = [
                block.translated_text for block in page_blocks if block.translated_text
            ] + [
                cell.translated_content
                for table in page_tables
                for cell in table.cells
                if cell.translated_content
            ]
            translated_text = "\n\n".join(translated_parts)
            results.append(
                PageResult(
                    document_id=document.document_id,
                    document_status=final_status,
                    page=page.model_copy(update={"translated_text": translated_text or None}),
                    blocks=page_blocks,
                    tables=page_tables,
                    warnings=[warning for block in page_blocks for warning in block.warnings]
                    + [
                        warning
                        for table in page_tables
                        for cell in table.cells
                        for warning in cell.warnings
                    ],
                )
            )
        return results
