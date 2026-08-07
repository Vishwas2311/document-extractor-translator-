from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import TranslationStatus


class Point(BaseModel):
    x: float
    y: float


class Span(BaseModel):
    offset: int
    length: int


class BoundingRegion(BaseModel):
    page_number: int
    polygon: list[Point] = Field(default_factory=list)


class TableCell(BaseModel):
    cell_id: str
    row_index: int
    column_index: int
    row_span: int = 1
    column_span: int = 1
    content: str = ""
    source_language: str = "und"
    translated_content: str | None = None
    translation_status: TranslationStatus = TranslationStatus.PENDING
    review_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    kind: str | None = None
    spans: list[Span] = Field(default_factory=list)
    bounding_regions: list[BoundingRegion] = Field(default_factory=list)
    origin: Literal["provider", "reconstructed"] = "provider"
    source_block_ids: list[str] = Field(default_factory=list)
    reconciliation_candidate_id: str | None = None


class TableResult(BaseModel):
    table_id: str
    row_count: int
    column_count: int
    cells: list[TableCell] = Field(default_factory=list)
    bounding_regions: list[BoundingRegion] = Field(default_factory=list)
    provider_row_count: int | None = None
    provider_column_count: int | None = None
    integrity_status: Literal["provider", "reconciled", "suspected_incomplete"] = "provider"
    reconciliation_candidate_id: str | None = None


class TextBlock(BaseModel):
    block_id: str
    reading_order: int
    source_text: str
    source_language: str = "und"
    translated_text: str | None = None
    translation_status: TranslationStatus = TranslationStatus.PENDING
    role: str | None = None
    spans: list[Span] = Field(default_factory=list)
    bounding_regions: list[BoundingRegion] = Field(default_factory=list)
    ocr_confidence: float | None = None
    confidence_source: Literal["word_length_weighted_mean"] | None = None
    review_required: bool = False
    warnings: list[str] = Field(default_factory=list)


class PageMetadata(BaseModel):
    page_number: int
    page_count: int
    width: float
    height: float
    unit: str
    angle: float = 0.0
    source_text: str = ""
    translated_text: str | None = None


class PageResult(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    document_status: str
    page: PageMetadata
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    filename: str
    status: str
    source_languages: list[str] = Field(default_factory=list)
    target_language: str = "en"
    pages: list[PageMetadata] = Field(default_factory=list)
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
