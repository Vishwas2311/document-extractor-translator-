from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import TERMINAL_DOCUMENT_STATUSES, DocumentStatus, JobStatus
from app.core.exceptions import ConflictError, DocumentNotFoundError, JobNotFoundError
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
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob).where(ProcessingJob.id == job_id).values(**values)
                ),
            )
            if result.rowcount == 0:
                raise JobNotFoundError("Processing job was not found.")
            await session.commit()

    async def claim_job(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        """Atomically claim a job for this worker if it is unclaimed or its lease expired.

        Uses a single conditional UPDATE (compare-and-swap) rather than a read-then-write,
        so two workers racing to claim the same job can never both succeed - the loser's
        UPDATE simply matches zero rows.
        """
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job_id,
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
                    .where(ProcessingJob.id == job_id, ProcessingJob.lease_owner == worker_id)
                    .values(
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        heartbeat_at=now,
                    )
                ),
            )
            await session.commit()
            return result.rowcount > 0

    async def finish_processing(
        self,
        document_id: str,
        job_id: str,
        *,
        document_values: dict[str, object],
        job_values: dict[str, object],
    ) -> None:
        """Write the terminal document status and job status in a single transaction.

        Both updates commit together so a crash between them can never leave the job
        stuck at RUNNING while its document already shows a terminal status.
        """
        document_values = {**document_values, "updated_at": datetime.now(UTC)}
        async with self.session_factory() as session:
            doc_result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document).where(Document.id == document_id).values(**document_values)
                ),
            )
            if doc_result.rowcount == 0:
                raise DocumentNotFoundError("Document was not found.")
            job_result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ProcessingJob).where(ProcessingJob.id == job_id).values(**job_values)
                ),
            )
            if job_result.rowcount == 0:
                raise JobNotFoundError("Processing job was not found.")
            await session.commit()

    async def create_retry_job(self, document_id: str) -> ProcessingJob:
        """Transition a document back to queued and enqueue a retry job, atomically.

        The eligibility check (status is failed/needs_review) and the transition are the
        same guarded UPDATE, so two concurrent retry requests can't both pass the check:
        only the first commits a row change, the second sees rowcount == 0 and is told
        the document is no longer in a retryable state instead of silently creating a
        second, orphaned job.
        """
        async with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Document)
                    .where(
                        Document.id == document_id,
                        Document.status.in_(
                            [DocumentStatus.FAILED.value, DocumentStatus.NEEDS_REVIEW.value]
                        ),
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
                raise ConflictError("Only failed or reviewable documents can be retried.")

            latest = await session.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.document_id == document_id)
                .order_by(ProcessingJob.created_at.desc())
                .limit(1)
            )
            job = ProcessingJob(
                document_id=document_id,
                attempt_number=(latest.attempt_number + 1) if latest else 1,
                status=JobStatus.QUEUED.value,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
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
