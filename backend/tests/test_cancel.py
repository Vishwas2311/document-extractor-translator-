"""Cancel + recovery semantics for documents and jobs."""

from pathlib import Path
from uuid import uuid4

from app.core.enums import DocumentStatus, JobStatus
from app.core.exceptions import ConflictError
from app.database.session import Database
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.repositories.documents import DocumentRepository


async def _new_repository(tmp_path: Path) -> tuple[DocumentRepository, Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    await database.create_schema()
    await database.ensure_prd_columns()
    return DocumentRepository(database.session_factory), database


async def _seed(repository: DocumentRepository, *, status: str) -> tuple[str, str]:
    document_id = str(uuid4())
    document = Document(
        id=document_id,
        original_filename="large.pdf",
        stored_extension="pdf",
        content_type="application/pdf",
        file_size=10,
        sha256="1" * 64,
        status=status,
    )
    job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED.value)
    await repository.create(document, job)
    return document_id, job.id


async def test_cancel_marks_document_and_job_terminal(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, job_id = await _seed(repository, status=DocumentStatus.TRANSLATING.value)
        assert await repository.claim_job(job_id, "worker-a", 300)

        cancelled = await repository.cancel_document(document_id)
        assert cancelled.status == DocumentStatus.CANCELLED.value
        assert cancelled.error_code == "cancelled"

        job = await repository.latest_job(document_id)
        assert job.status == JobStatus.CANCELLED.value
        assert job.lease_owner is None
        assert not await repository.claim_job(job_id, "worker-b", 300)
        assert document_id not in await repository.recoverable_document_ids()
    finally:
        await database.dispose()


async def test_cancelled_document_is_not_recoverable_after_restart(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed(repository, status=DocumentStatus.EXTRACTING.value)
        await repository.cancel_document(document_id)

        recoverable = await repository.recoverable_document_ids()
        assert document_id not in recoverable
        assert await repository.is_cancelled(document_id)
    finally:
        await database.dispose()


async def test_cancel_is_idempotent_and_blocks_completed(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed(repository, status=DocumentStatus.QUEUED.value)
        first = await repository.cancel_document(document_id)
        second = await repository.cancel_document(document_id)
        assert first.status == DocumentStatus.CANCELLED.value
        assert second.status == DocumentStatus.CANCELLED.value

        done_id, _ = await _seed(repository, status=DocumentStatus.COMPLETED.value)
        try:
            await repository.cancel_document(done_id)
            raise AssertionError("expected ConflictError")
        except ConflictError:
            pass
    finally:
        await database.dispose()


async def test_cancelled_documents_can_be_retried(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed(repository, status=DocumentStatus.QUEUED.value)
        await repository.cancel_document(document_id)
        job = await repository.create_retry_job(document_id)
        document = await repository.get(document_id)
        assert document.status == DocumentStatus.QUEUED.value
        assert job.status == JobStatus.QUEUED.value
        assert document_id in await repository.recoverable_document_ids()
    finally:
        await database.dispose()


async def test_finish_processing_does_not_overwrite_cancelled(tmp_path: Path) -> None:
    from app.core.exceptions import JobCancelledError

    repository, database = await _new_repository(tmp_path)
    try:
        document_id, job_id = await _seed(repository, status=DocumentStatus.TRANSLATING.value)
        assert await repository.claim_job(job_id, "worker-a", 300)
        await repository.cancel_document(document_id)

        try:
            await repository.finish_processing(
                document_id,
                job_id,
                document_values={
                    "status": DocumentStatus.COMPLETED.value,
                    "current_stage": DocumentStatus.COMPLETED.value,
                    "progress_percent": 100,
                },
                job_values={
                    "status": JobStatus.COMPLETED.value,
                    "lease_owner": None,
                    "lease_expires_at": None,
                },
                lease_owner="worker-a",
            )
            raise AssertionError("expected JobCancelledError")
        except JobCancelledError:
            pass

        document = await repository.get(document_id)
        assert document.status == DocumentStatus.CANCELLED.value
    finally:
        await database.dispose()


async def test_old_job_writes_fail_after_retry_supersedes(tmp_path: Path) -> None:
    from app.core.exceptions import JobSupersededError

    repository, database = await _new_repository(tmp_path)
    try:
        document_id, old_job_id = await _seed(repository, status=DocumentStatus.QUEUED.value)
        await repository.cancel_document(document_id)
        new_job = await repository.create_retry_job(document_id)

        try:
            await repository.update_active_document(
                document_id,
                job_id=old_job_id,
                progress_percent=55,
                status=DocumentStatus.TRANSLATING.value,
            )
            raise AssertionError("expected JobSupersededError")
        except JobSupersededError:
            pass

        await repository.update_active_document(
            document_id,
            job_id=new_job.id,
            progress_percent=10,
            status=DocumentStatus.EXTRACTING.value,
        )
        document = await repository.get(document_id)
        assert document.status == DocumentStatus.EXTRACTING.value
        assert document.progress_percent == 10
    finally:
        await database.dispose()


async def test_update_active_job_rejects_cancelled_job(tmp_path: Path) -> None:
    from app.core.exceptions import JobCancelledError

    repository, database = await _new_repository(tmp_path)
    try:
        document_id, job_id = await _seed(repository, status=DocumentStatus.TRANSLATING.value)
        assert await repository.claim_job(job_id, "worker-a", 300)
        await repository.cancel_document(document_id)
        try:
            await repository.update_active_job(job_id, stage="translating")
            raise AssertionError("expected JobCancelledError")
        except JobCancelledError:
            pass
        job = await repository.latest_job(document_id)
        assert job.status == JobStatus.CANCELLED.value
        assert job.stage == DocumentStatus.CANCELLED.value
    finally:
        await database.dispose()


async def test_queue_metrics_only_count_queued_ahead(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        first_id, _ = await _seed(repository, status=DocumentStatus.QUEUED.value)
        second_id, _ = await _seed(repository, status=DocumentStatus.QUEUED.value)
        busy_id, busy_job = await _seed(repository, status=DocumentStatus.TRANSLATING.value)
        assert await repository.claim_job(busy_job, "worker-a", 300)

        first = await repository.queue_metrics(first_id)
        second = await repository.queue_metrics(second_id)
        busy = await repository.queue_metrics(busy_id)

        assert first["queue_position"] == 1
        assert second["queue_position"] == 2
        assert busy["queue_position"] is None
        assert busy["active_jobs"] == 1
    finally:
        await database.dispose()
