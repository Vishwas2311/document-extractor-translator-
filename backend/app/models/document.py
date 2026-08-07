from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentStatus
from app.core.versioning import CURRENT_PROCESSING_VERSION
from app.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "financial_review_status IS NULL OR "
            "financial_review_status IN ('approved', 'rejected')",
            name="ck_documents_financial_review_status",
        ),
        CheckConstraint(
            "translation_review_status IS NULL OR "
            "translation_review_status IN ('approved', 'rejected')",
            name="ck_documents_translation_review_status",
        ),
        CheckConstraint(
            "document_review_status IN "
            "('draft', 'needs_review', 'in_review', 'approved', 'rejected')",
            name="ck_documents_document_review_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_extension: Mapped[str] = mapped_column(String(12))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=DocumentStatus.UPLOADED.value, index=True
    )
    current_stage: Mapped[str] = mapped_column(String(32), default="uploaded")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_ready: Mapped[int | None] = mapped_column(Integer, nullable=True)
    translation_batches_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    translation_batches_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    financial_extraction_mode: Mapped[str] = mapped_column(
        String(32), default="post_extract"
    )
    financial_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uncertain_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    financial_table_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    financial_issue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    financial_result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    financial_review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    financial_reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    financial_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(64), default="org-local", index=True
    )
    owner_subject: Mapped[str] = mapped_column(
        String(255), default="local-api-token", index=True
    )
    assigned_reviewer_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    assignment_status: Mapped[str] = mapped_column(String(32), default="unassigned")
    document_review_status: Mapped[str] = mapped_column(
        String(32), default="draft", index=True
    )
    translation_result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    translation_review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    translation_reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    translation_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_language: Mapped[str] = mapped_column(String(12), default="en")
    data_class: Mapped[str] = mapped_column(String(32), default="synthetic")
    processing_profile: Mapped[str] = mapped_column(String(64), default="GENAI_PSEUDONYMIZED")
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    processing_version: Mapped[str] = mapped_column(
        String(32), default=CURRENT_PROCESSING_VERSION
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    jobs = relationship("ProcessingJob", back_populates="document", cascade="all, delete-orphan")
    financial_reviews = relationship(
        "FinancialReview",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    translation_reviews = relationship(
        "TranslationReview",
        back_populates="document",
        cascade="all, delete-orphan",
    )
