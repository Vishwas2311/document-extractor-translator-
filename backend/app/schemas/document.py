from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProcessingInfo(BaseModel):
    current_stage: str
    progress_percent: int
    attempt: int = 1
    warnings: list[str] = Field(default_factory=list)


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
    pages_ready: int | None = None
    translation_batches_done: int | None = None
    translation_batches_total: int | None = None
    financial_extraction_mode: str = "post_extract"
    financial_page_count: int | None = None
    uncertain_page_count: int | None = None
    financial_table_count: int | None = None
    financial_issue_count: int | None = None
    financial_result_sha256: str | None = None
    financial_review_status: str | None = None
    financial_reviewed_by: str | None = None
    financial_reviewed_at: datetime | None = None
    organization_id: str = "org-local"
    owner_subject: str = "local-api-token"
    assigned_reviewer_subject: str | None = None
    assignment_status: str = "unassigned"
    document_review_status: str = "draft"
    translation_result_sha256: str | None = None
    translation_review_status: str | None = None
    translation_reviewed_by: str | None = None
    translation_reviewed_at: datetime | None = None
    source_languages: list[str] = Field(default_factory=list)
    target_language: str
    data_class: str = "synthetic"
    processing_profile: str = "GENAI_PSEUDONYMIZED"
    error_code: str | None = None
    safe_error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    # Runtime queue observability (filled by the API, not persisted).
    queue_position: int | None = None
    active_jobs: int | None = None
    worker_slots: int | None = None


class DocumentDetail(DocumentSummary):
    schema_version: str
    processing_version: str


class DocumentCreateResponse(BaseModel):
    document_id: str
    status: str
    status_url: str
    processing_profile: str | None = None
    data_class: str | None = None


class CancelDocumentResponse(BaseModel):
    document_id: str
    status: str
    message: str


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
    review_required: bool = False
    financial_label: str | None = None
    financial_confidence: float | None = None
    financial_disposition: str | None = None
    financial_selected: bool = False
    financial_reason: list[str] = Field(default_factory=list)
    financial_table_count: int = 0
    validation_issue_count: int = 0
