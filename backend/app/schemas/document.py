from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProcessingInfo(BaseModel):
    current_stage: str
    progress_percent: int
    attempt: int = 1
    warnings: list[str] = Field(default_factory=list)


class DocumentCreateResponse(BaseModel):
    document_id: str
    status: str
    status_url: str


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    content_type: str
    file_size: int
    status: str
    current_stage: str
    progress_percent: int
    page_count: int | None = None
    source_languages: list[str] = Field(default_factory=list)
    target_language: str
    error_code: str | None = None
    safe_error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DocumentDetail(DocumentSummary):
    schema_version: str
    processing_version: str


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    page: int
    page_size: int
    total: int


class PageSummary(BaseModel):
    page_number: int
    width: float
    height: float
    unit: str
    angle: float
    block_count: int
    table_count: int
