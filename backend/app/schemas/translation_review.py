"""Versioned contracts for translation review decisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranslationCorrection(BaseModel):
    target_kind: Literal["block", "cell"]
    target_id: str = Field(min_length=1, max_length=128)
    page_number: int = Field(ge=1)
    corrected_translated_text: str = Field(min_length=0, max_length=20000)
    reason: str = Field(min_length=1, max_length=500)


class TranslationReviewCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)
    corrections: list[TranslationCorrection] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def unique_corrections(self) -> "TranslationReviewCreate":
        keys = [(item.target_kind, item.target_id) for item in self.corrections]
        if len(keys) != len(set(keys)):
            raise ValueError("A translation target can have only one correction per review.")
        return self


class TranslationReviewRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    decision: Literal["approved", "rejected"]
    reviewer_subject: str
    note: str | None = None
    corrections: list[TranslationCorrection] = Field(default_factory=list)
    processing_version: str
    result_schema_version: str
    result_sha256: str
    created_at: datetime
    active_result: bool = False


class TranslationReviewHistory(BaseModel):
    items: list[TranslationReviewRecord] = Field(default_factory=list)
