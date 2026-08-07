"""Versioned contracts for deterministic table-integrity reconciliation."""

from typing import Literal

from pydantic import BaseModel, Field


class ReconciliationEvidence(BaseModel):
    """One content-free reason supporting a structural reconciliation."""

    code: str
    score: float = Field(ge=0, le=1)
    detail: str


class TableReconciliationCandidate(BaseModel):
    """A proposed provider-table repair built only from source OCR evidence."""

    candidate_id: str
    table_id: str
    page_number: int = Field(ge=1)
    action: Literal["prepend_columns", "append_columns"]
    provider_row_count: int = Field(ge=1)
    provider_column_count: int = Field(ge=1)
    proposed_row_count: int = Field(ge=1)
    proposed_column_count: int = Field(ge=1)
    added_cell_count: int = Field(ge=1)
    consumed_block_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[ReconciliationEvidence] = Field(min_length=1)
    review_required: bool = True


class TableReconciliationResult(BaseModel):
    """Document-level audit artifact for table-integrity decisions."""

    schema_version: str = "table-reconciliation-1.0"
    document_id: str
    algorithm_version: str = "aligned-orphan-columns-1.0"
    algorithm_fingerprint: str
    candidate_count: int = Field(ge=0)
    candidates: list[TableReconciliationCandidate] = Field(default_factory=list)
