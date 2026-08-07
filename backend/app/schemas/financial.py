"""Versioned contracts for financial-page selection and normalized results."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import FinancialPageDisposition
from app.schemas.page import BoundingRegion


class FinancialClassificationEvidence(BaseModel):
    """One provider label observed for a source page."""

    label: str
    confidence: float = Field(ge=0, le=1)


class FinancialPageClassification(BaseModel):
    page_number: int = Field(ge=1)
    label: str
    confidence: float = Field(ge=0, le=1)
    disposition: FinancialPageDisposition
    selected: bool
    review_required: bool = False
    reasons: list[str] = Field(default_factory=list)
    candidates: list[FinancialClassificationEvidence] = Field(default_factory=list)
    source: Literal["azure_custom_classifier", "layout_rules", "adjacent_page"]


class FinancialClassificationResult(BaseModel):
    schema_version: str = "financial-classification-1.1"
    document_id: str
    classifier_id: str
    classifier_version: str
    selection_policy_fingerprint: str = ""
    source_page_count: int = Field(ge=1)
    pages: list[FinancialPageClassification]

    @model_validator(mode="after")
    def complete_page_coverage(self) -> "FinancialClassificationResult":
        page_numbers = [page.page_number for page in self.pages]
        expected = list(range(1, self.source_page_count + 1))
        if sorted(page_numbers) != expected:
            raise ValueError(
                "Financial classification must contain exactly one decision per source page."
            )
        return self

    @property
    def selected_pages(self) -> list[int]:
        return sorted(page.page_number for page in self.pages if page.selected)


class NormalizedFinancialValue(BaseModel):
    raw_text: str
    normalized_value: Decimal | None = None
    value_type: Literal["amount", "percentage", "text", "empty"] = "text"
    semantic_type: Literal[
        "monetary_amount",
        "percentage",
        "percentage_range",
        "quantity",
        "measurement",
        "phone_number",
        "date_or_time",
        "account_number",
        "identifier",
        "text",
        "empty",
        "unknown_numeric",
    ] = "text"
    currency: str | None = None
    currency_candidates: list[str] = Field(default_factory=list)
    currency_source: Literal["explicit_code", "symbol", "page_context"] | None = None
    currency_ambiguous: bool = False
    negative: bool = False
    ambiguous: bool = False
    requires_normalized_correction: bool = False
    requires_currency_correction: bool = False
    review_reason_code: Literal[
        "ambiguous_monetary_separator",
        "ambiguous_currency",
        "malformed_monetary_value",
    ] | None = None
    normalization_status: Literal[
        "parsed", "ambiguous", "unparsed", "empty", "not_applicable"
    ] = "unparsed"

    @model_validator(mode="after")
    def correction_flags_are_monetary(self) -> "NormalizedFinancialValue":
        if (
            self.requires_normalized_correction
            or self.requires_currency_correction
        ) and self.semantic_type != "monetary_amount":
            raise ValueError("Only monetary amounts can require financial corrections.")
        if self.requires_normalized_correction and not self.ambiguous:
            raise ValueError("A required normalized correction must be ambiguous.")
        if self.requires_currency_correction and not self.currency_ambiguous:
            raise ValueError("A required currency correction must have ambiguous currency.")
        return self


class FinancialCell(BaseModel):
    cell_id: str
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    kind: str | None = None
    source_language: str = "und"
    translated_text: str | None = None
    value: NormalizedFinancialValue
    source_page: int = Field(ge=1)
    bounding_regions: list[BoundingRegion] = Field(default_factory=list)
    review_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    origin: Literal["provider", "reconstructed"] = "provider"
    source_block_ids: list[str] = Field(default_factory=list)
    reconciliation_candidate_id: str | None = None


class FinancialTable(BaseModel):
    table_id: str
    source_pages: list[int]
    financial_type: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    currencies: list[str] = Field(default_factory=list)
    cells: list[FinancialCell] = Field(default_factory=list)
    merge_policy: Literal[
        "provider_table_atomic_v1", "provider_table_with_reconciliation_v1"
    ] = "provider_table_atomic_v1"
    complete: bool = True
    missing_source_pages: list[int] = Field(default_factory=list)
    classification_override_pages: list[int] = Field(default_factory=list)
    review_required: bool = False
    provider_row_count: int | None = None
    provider_column_count: int | None = None
    integrity_status: Literal["provider", "reconciled", "suspected_incomplete"] = "provider"
    reconciliation_candidate_id: str | None = None
    relevance: Literal["financial", "uncertain"] = "uncertain"


class FinancialContentItem(BaseModel):
    """One format-preserving financial element in source reading order."""

    item_id: str
    item_type: Literal["heading", "paragraph", "key_value", "list_item", "table"]
    reading_order: int = Field(ge=1)
    source_pages: list[int] = Field(min_length=1)
    source_language: str = "und"
    source_text: str | None = None
    translated_text: str | None = None
    role: str | None = None
    key: str | None = None
    value: str | None = None
    translated_key: str | None = None
    translated_value: str | None = None
    table_id: str | None = None
    relevance: Literal["financial", "supporting", "uncertain"]
    bounding_regions: list[BoundingRegion] = Field(default_factory=list)
    review_required: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_payload_for_type(self) -> "FinancialContentItem":
        if self.item_type == "table":
            if not self.table_id:
                raise ValueError("A financial table content item requires table_id.")
            return self
        if self.source_text is None:
            raise ValueError("A financial text content item requires source_text.")
        if self.item_type == "key_value" and (self.key is None or self.value is None):
            raise ValueError("A financial key-value content item requires key and value.")
        return self


class FinancialValidationIssue(BaseModel):
    issue_id: str
    severity: Literal["warning", "error"]
    code: str
    message: str
    page_number: int | None = None
    table_id: str | None = None
    cell_id: str | None = None


class FinancialValidationReport(BaseModel):
    schema_version: str = "financial-validation-1.3"
    document_id: str
    issue_count: int
    error_count: int
    warning_count: int
    review_required: bool
    issues: list[FinancialValidationIssue] = Field(default_factory=list)


class FinancialResult(BaseModel):
    schema_version: str = "financial-result-1.4"
    document_id: str
    processing_version: str
    source_page_count: int = Field(ge=1)
    selected_pages: list[int]
    uncertain_pages: list[int] = Field(default_factory=list)
    content_items: list[FinancialContentItem] = Field(default_factory=list)
    tables: list[FinancialTable] = Field(default_factory=list)
    validation: FinancialValidationReport
    reconciliation_candidate_ids: list[str] = Field(default_factory=list)


class FinancialStructureDecision(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)


class FinancialCorrection(BaseModel):
    cell_id: str = Field(min_length=1, max_length=128)
    normalized_value: Decimal | None = Field(default=None, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=1, max_length=1000)


class FinancialReviewCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=4000)
    corrections: list[FinancialCorrection] = Field(default_factory=list, max_length=500)
    structure_decisions: list[FinancialStructureDecision] = Field(
        default_factory=list, max_length=500
    )

    @model_validator(mode="after")
    def unique_corrections(self) -> "FinancialReviewCreate":
        cell_ids = [correction.cell_id for correction in self.corrections]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("A financial cell can have only one correction per review.")
        candidate_ids = [item.candidate_id for item in self.structure_decisions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("A reconstruction candidate can have only one decision per review.")
        return self


class FinancialReviewRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    decision: Literal["approved", "rejected"]
    reviewer_subject: str
    note: str | None = None
    corrections: list[FinancialCorrection] = Field(default_factory=list)
    structure_decisions: list[FinancialStructureDecision] = Field(default_factory=list)
    processing_version: str
    result_schema_version: str
    result_sha256: str
    active_result: bool = False
    created_at: datetime


class FinancialReviewHistory(BaseModel):
    items: list[FinancialReviewRecord] = Field(default_factory=list)
