from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentStatus
from app.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

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
    source_languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_language: Mapped[str] = mapped_column(String(12), default="en")
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    processing_version: Mapped[str] = mapped_column(String(32), default="poc-1")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    jobs = relationship("ProcessingJob", back_populates="document", cascade="all, delete-orphan")
    translation_batches = relationship(
        "TranslationBatch", back_populates="document", cascade="all, delete-orphan"
    )
