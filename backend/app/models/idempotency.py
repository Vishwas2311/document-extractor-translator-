"""Idempotency records so a retried mutation cannot run twice.

Binds a client-supplied ``Idempotency-Key`` to the tenant, principal, operation,
and a fingerprint of the request. A repeated request with the same key returns
the stored response instead of creating a second document (and a second billable
Azure run); the same key with a different body is rejected.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", name="uq_idempotency_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # scope = sha256(organization_id, actor_subject, operation, key) - see
    # app.core.idempotency.idempotency_scope for why it's hashed rather than
    # delimited-concatenated.
    scope: Mapped[str] = mapped_column(String(512), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    # 0 marks a reservation that is still in flight; a real HTTP status marks a
    # completed request whose response body can be safely replayed.
    response_status: Mapped[int] = mapped_column(Integer, default=0)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
