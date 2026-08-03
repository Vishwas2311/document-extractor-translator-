from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import (
    RETRIABLE_DOCUMENT_STATUSES,
    TERMINAL_DOCUMENT_STATUSES,
    DocumentStatus,
    JobStatus,
    RetryMode,
)
from app.core.exceptions import (
    ConflictError,
    DocumentNotFoundError,
    JobCancelledError,
    JobLeaseLostError,
    JobNotFoundError,
    JobSupersededError,
)
from app.models.document import Document
from app.models.processing_job import ProcessingJob

CLAIMABLE_JOB_STATUSES = {JobStatus.QUEUED.value, JobStatus.RUNNING.value}


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

    async def _latest_job_locked(self, session: AsyncSession, document_id: str) -> ProcessingJob:
        job = await session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document_id)
            .order_by(
                ProcessingJob.created_at.desc(),
                ProcessingJob.attempt_number.desc(),
            )
            .limit(1)
        )
        if job is None:
            raise DocumentNotFoundError("Processing job was not found.")
        return job

    async def assert_job_is_current(self, document_id: str, job_id: str) -> None:
        """Fail if this job was cancelled or replaced by a newer retry."""
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise DocumentNotFoundError("Document was not found.")
            if document.status == DocumentStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")
            latest = await self._latest_job_locked(session, document_id)
            if latest.id != job_id:
                raise JobSupersededError("A newer processing job replaced this worker.")
            if latest.status == JobStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")

    async def update_active_document(
        self,
        document_id: str,
        *,
        job_id: str,
        **values: object,
    ) -> None:
        """Update only while this job owns the document and it is still non-terminal."""
        values["updated_at"] = datetime.now(UTC)
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise DocumentNotFoundError("Document was not found.")
            if document.status == DocumentStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")

            latest = await self._latest_job_locked(session, document_id)
            if latest.id != job_id:
                raise JobSupersededError("A newer processing job replaced this worker.")
            if latest.status == JobStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")

            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document)
                    .where(Document.id == document_id, Document.status.not_in(terminal))
                    .values(**values)
                ),
            )
            if result.rowcount == 0:
                document = await session.get(Document, document_id)
                if document is None:
                    raise DocumentNotFoundError("Document was not found.")
                if document.status == DocumentStatus.CANCELLED.value:
                    raise JobCancelledError("Processing was cancelled.")
                raise ConflictError("Document is no longer active.")
            await session.commit()

    async def latest_job(self, document_id: str) -> ProcessingJob:
        async with self.session_factory() as session:
            return await self._latest_job_locked(session, document_id)

    async def update_job(self, job_id: str, **values: object) -> None:
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob).where(ProcessingJob.id == job_id).values(**values)
                ),
            )
            if result.rowcount == 0:
                raise JobNotFoundError("Processing job was not found.")
            await session.commit()

    async def update_active_job(self, job_id: str, **values: object) -> None:
        """Update job metadata only while the job is still claimable (not cancelled)."""
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job_id,
                        ProcessingJob.status.in_(list(CLAIMABLE_JOB_STATUSES)),
                    )
                    .values(**values)
                ),
            )
            if result.rowcount == 0:
                job = await session.get(ProcessingJob, job_id)
                if job is None:
                    raise JobNotFoundError("Processing job was not found.")
                if job.status == JobStatus.CANCELLED.value:
                    raise JobCancelledError("Processing was cancelled.")
                raise ConflictError("Processing job is no longer active.")
            await session.commit()

    async def claim_job(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        """Atomically claim a non-terminal job if unclaimed or lease expired."""
        now = datetime.now(UTC)
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job_id,
                        ProcessingJob.status.in_(list(CLAIMABLE_JOB_STATUSES)),
                        ProcessingJob.document_id.in_(
                            select(Document.id).where(Document.status.not_in(terminal))
                        ),
                        or_(
                            ProcessingJob.lease_owner.is_(None),
                            ProcessingJob.lease_expires_at.is_(None),
                            ProcessingJob.lease_expires_at < now,
                        ),
                    )
                    .values(
                        status=JobStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        started_at=now,
                        heartbeat_at=now,
                    )
                ),
            )
            await session.commit()
            return result.rowcount > 0

    async def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        """Extend this worker's lease. Returns False if the lease was reclaimed elsewhere."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job_id,
                        ProcessingJob.lease_owner == worker_id,
                        ProcessingJob.status == JobStatus.RUNNING.value,
                    )
                    .values(
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        heartbeat_at=now,
                    )
                ),
            )
            await session.commit()
            return result.rowcount > 0

    async def clear_stale_leases(self) -> int:
        """Release leases for non-terminal jobs so recovery can reclaim them."""
        now = datetime.now(UTC)
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.status.in_(list(CLAIMABLE_JOB_STATUSES)),
                        ProcessingJob.document_id.in_(
                            select(Document.id).where(Document.status.not_in(terminal))
                        ),
                        or_(
                            ProcessingJob.lease_expires_at.is_(None),
                            ProcessingJob.lease_expires_at < now,
                        ),
                    )
                    .values(lease_owner=None, lease_expires_at=None)
                ),
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def cancel_document(self, document_id: str) -> Document:
        """Mark a non-terminal document and its active job as cancelled."""
        now = datetime.now(UTC)
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise DocumentNotFoundError("Document was not found.")
            if document.status == DocumentStatus.CANCELLED.value:
                return document
            if document.status in terminal:
                raise ConflictError("Only in-progress documents can be cancelled.")

            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document)
                    .where(
                        Document.id == document_id,
                        Document.status.not_in(terminal),
                    )
                    .values(
                        status=DocumentStatus.CANCELLED.value,
                        current_stage=DocumentStatus.CANCELLED.value,
                        error_code="cancelled",
                        safe_error_message="Processing was cancelled.",
                        completed_at=now,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount == 0:
                current = await session.get(Document, document_id)
                if current is None:
                    raise DocumentNotFoundError("Document was not found.")
                if current.status == DocumentStatus.CANCELLED.value:
                    return current
                raise ConflictError("Only in-progress documents can be cancelled.")

            await session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.document_id == document_id,
                    ProcessingJob.status.in_(list(CLAIMABLE_JOB_STATUSES)),
                )
                .values(
                    status=JobStatus.CANCELLED.value,
                    stage=DocumentStatus.CANCELLED.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    completed_at=now,
                    error_code="cancelled",
                    safe_error_message="Processing was cancelled.",
                )
            )
            await session.commit()
            cancelled = await session.get(Document, document_id)
            assert cancelled is not None
            return cancelled

    async def is_cancelled(self, document_id: str) -> bool:
        document = await self.get(document_id)
        return document.status == DocumentStatus.CANCELLED.value

    async def queue_metrics(self, document_id: str) -> dict[str, int | None]:
        """Queue position among queued docs only; plus active running job count."""
        terminal = [status.value for status in TERMINAL_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise DocumentNotFoundError("Document was not found.")
            if document.status in terminal:
                return {"queue_position": None, "active_jobs": None}

            active = await session.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.status == JobStatus.RUNNING.value)
            )

            if document.status != DocumentStatus.QUEUED.value:
                return {
                    "queue_position": None,
                    "active_jobs": int(active or 0),
                }

            ahead = await session.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.status == DocumentStatus.QUEUED.value,
                    Document.id != document_id,
                    Document.created_at <= document.created_at,
                )
            )
            return {
                "queue_position": int(ahead or 0) + 1,
                "active_jobs": int(active or 0),
            }

    async def finish_processing(
        self,
        document_id: str,
        job_id: str,
        *,
        document_values: dict[str, object],
        job_values: dict[str, object],
        lease_owner: str | None = None,
    ) -> None:
        """Write terminal document+job status. When lease_owner is set, require ownership."""
        document_values = {**document_values, "updated_at": datetime.now(UTC)}
        async with self.session_factory() as session:
            current = await session.get(Document, document_id)
            if current is None:
                raise DocumentNotFoundError("Document was not found.")
            if current.status == DocumentStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")

            latest = await self._latest_job_locked(session, document_id)
            if latest.id != job_id:
                raise JobSupersededError("A newer processing job replaced this worker.")
            if latest.status == JobStatus.CANCELLED.value:
                raise JobCancelledError("Processing was cancelled.")

            doc_result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document)
                    .where(
                        Document.id == document_id,
                        Document.status != DocumentStatus.CANCELLED.value,
                    )
                    .values(**document_values)
                ),
            )
            if doc_result.rowcount == 0:
                raise JobCancelledError("Processing was cancelled.")

            job_where = [
                ProcessingJob.id == job_id,
                ProcessingJob.status != JobStatus.CANCELLED.value,
            ]
            if lease_owner is not None:
                job_where.append(ProcessingJob.lease_owner == lease_owner)

            job_result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob).where(*job_where).values(**job_values)
                ),
            )
            if job_result.rowcount == 0:
                cancelled_job = await session.get(ProcessingJob, job_id)
                if cancelled_job is not None and cancelled_job.status == JobStatus.CANCELLED.value:
                    raise JobCancelledError("Processing was cancelled.")
                if lease_owner is not None:
                    raise JobLeaseLostError(
                        "This worker's job lease expired and was reclaimed by another worker."
                    )
                raise JobNotFoundError("Processing job was not found.")
            await session.commit()

    async def create_retry_job(
        self,
        document_id: str,
        *,
        mode: RetryMode = RetryMode.RESUME,
    ) -> ProcessingJob:
        """Transition a document back to queued and enqueue a retry job, atomically."""
        retriable = [status.value for status in RETRIABLE_DOCUMENT_STATUSES]
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document)
                    .where(
                        Document.id == document_id,
                        Document.status.in_(retriable),
                    )
                    .values(
                        status=DocumentStatus.QUEUED.value,
                        current_stage="queued",
                        progress_percent=0,
                        error_code=None,
                        safe_error_message=None,
                        completed_at=None,
                        updated_at=datetime.now(UTC),
                    )
                ),
            )
            if result.rowcount == 0:
                if await session.get(Document, document_id) is None:
                    raise DocumentNotFoundError("Document was not found.")
                raise ConflictError(
                    "Only failed, cancelled, or reviewable documents can be retried."
                )

            latest = await session.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.document_id == document_id)
                .order_by(
                    ProcessingJob.created_at.desc(),
                    ProcessingJob.attempt_number.desc(),
                )
                .limit(1)
            )
            job = ProcessingJob(
                document_id=document_id,
                attempt_number=(latest.attempt_number + 1) if latest else 1,
                status=JobStatus.QUEUED.value,
                stage=f"retry:{mode.value}",
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def recoverable_document_ids(self) -> Sequence[str]:
        """Non-terminal documents eligible for recovery re-enqueue (never cancelled)."""
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
