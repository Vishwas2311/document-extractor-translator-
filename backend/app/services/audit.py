"""Content-free audit event recording."""

from __future__ import annotations

from app.models.audit_event import AuditEvent
from app.repositories.documents import DocumentRepository


class AuditService:
    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def record(
        self,
        *,
        organization_id: str,
        actor_subject: str,
        action: str,
        resource_type: str,
        resource_id: str,
        result: str = "success",
        correlation_id: str | None = None,
        detail: str | None = None,
    ) -> AuditEvent:
        return await self.repository.create_audit_event(
            AuditEvent(
                organization_id=organization_id,
                actor_subject=actor_subject,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                correlation_id=correlation_id,
                detail=detail,
            )
        )
