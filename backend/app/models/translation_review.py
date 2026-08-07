"""Append-only translation review decisions bound to a bilingual result hash."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TranslationReview(Base):
    __tablename__ = "translation_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_translation_reviews_decision",
        ),
        CheckConstraint(
            "length(result_sha256) = 64",
            name="ck_translation_reviews_result_sha256_length",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reviewer_subject: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrections: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    processing_version: Mapped[str] = mapped_column(String(64))
    result_schema_version: Mapped[str] = mapped_column(String(64))
    result_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    document = relationship("Document", back_populates="translation_reviews")
