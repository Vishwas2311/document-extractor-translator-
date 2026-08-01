from app.schemas.page import CanonicalDocument, PageResult, TableResult, TextBlock


class ExportService:
    def page_results(
        self,
        document: CanonicalDocument,
        final_status: str,
    ) -> list[PageResult]:
        results: list[PageResult] = []
        for page in document.pages:
            page_blocks: list[TextBlock] = []
            for block in document.blocks:
                page_regions = [
                    region
                    for region in block.bounding_regions
                    if region.page_number == page.page_number
                ]
                if not page_regions:
                    continue
                page_blocks.append(block.model_copy(update={"bounding_regions": page_regions}))
            page_tables: list[TableResult] = []
            for table in document.tables:
                table_regions = [
                    region
                    for region in table.bounding_regions
                    if region.page_number == page.page_number
                ]
                page_cells = []
                for cell in table.cells:
                    cell_regions = [
                        region
                        for region in cell.bounding_regions
                        if region.page_number == page.page_number
                    ]
                    if cell_regions:
                        page_cells.append(
                            cell.model_copy(update={"bounding_regions": cell_regions})
                        )
                if table_regions or page_cells:
                    page_tables.append(
                        table.model_copy(
                            update={"bounding_regions": table_regions, "cells": page_cells}
                        )
                    )
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
