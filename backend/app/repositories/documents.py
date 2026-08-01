from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import TERMINAL_DOCUMENT_STATUSES, DocumentStatus, JobStatus
from app.core.exceptions import DocumentNotFoundError
from app.models.document import Document
from app.models.processing_job import ProcessingJob


class DocumentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create(self, document: Document, job: ProcessingJob) -> Document:
        async with self.session_factory() as session:
            session.add(document)
            session.add(job)
            await session.commit()
            await session.refresh(document)
            return document

    async def get(self, document_id: str) -> Document:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise DocumentNotFoundError("Document was not found.")
            return document

    async def list(self, page: int, page_size: int) -> tuple[Sequence[Document], int]:
        async with self.session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(Document)) or 0
            result = await session.scalars(
                select(Document)
                .order_by(Document.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return result.all(), total

    async def update_document(self, document_id: str, **values: object) -> None:
        values["updated_at"] = datetime.now(UTC)
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document).where(Document.id == document_id).values(**values)
                ),
            )
            if result.rowcount == 0:
                raise DocumentNotFoundError("Document was not found.")
            await session.commit()

    async def latest_job(self, document_id: str) -> ProcessingJob:
        async with self.session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.document_id == document_id)
                .order_by(ProcessingJob.created_at.desc())
                .limit(1)
            )
            if job is None:
                raise DocumentNotFoundError("Processing job was not found.")
            return job

    async def update_job(self, job_id: str, **values: object) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ProcessingJob).where(ProcessingJob.id == job_id).values(**values)
            )
            await session.commit()

    async def create_retry_job(self, document_id: str) -> ProcessingJob:
        latest = await self.latest_job(document_id)
        job = ProcessingJob(
            document_id=document_id,
            attempt_number=latest.attempt_number + 1,
            status=JobStatus.QUEUED.value,
        )
        async with self.session_factory() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)
        await self.update_document(
            document_id,
            status=DocumentStatus.QUEUED.value,
            current_stage="queued",
            progress_percent=0,
            error_code=None,
            safe_error_message=None,
            completed_at=None,
        )
        return job

    async def recoverable_document_ids(self) -> Sequence[str]:
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            result = await session.scalars(
                select(Document.id).where(Document.status.not_in(terminal))
            )
            return list(result.all())

    async def delete(self, document_id: str) -> None:
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(delete(Document).where(Document.id == document_id)),
            )
            if result.rowcount == 0:
                raise DocumentNotFoundError("Document was not found.")
            await session.commit()
