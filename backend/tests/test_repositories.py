"""Concurrency and atomicity tests for DocumentRepository.

These exercise real SQLite transactions (not fakes) because the behavior under test -
whether two concurrent operations can both "win" a guarded state transition - depends
on genuine transactional isolation, not on any particular Python-level mock.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.enums import DocumentStatus, JobStatus, RetryMode
from app.core.exceptions import ConflictError, JobNotFoundError
from app.database.session import Database
from app.models.document import Document
from app.models.financial_review import FinancialReview
from app.models.processing_job import ProcessingJob
from app.repositories.documents import DocumentRepository


async def _new_repository(tmp_path: Path) -> tuple[DocumentRepository, Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_schema()
    return DocumentRepository(database.session_factory), database


async def _seed_document(repository: DocumentRepository, *, status: str) -> tuple[str, str]:
    # Document.id has a Python-side default that SQLAlchemy only evaluates at flush time,
    # so it isn't populated on the instance until after commit - generate it up front
    # (as DocumentService.create_upload does) instead of reading document.id too early.
    document_id = str(uuid4())
    document = Document(
        id=document_id,
        original_filename="intake.pdf",
        stored_extension="pdf",
        content_type="application/pdf",
        file_size=10,
        sha256="0" * 64,
        status=status,
    )
    job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED.value)
    await repository.create(document, job)
    return document_id, job.id


async def test_claim_job_is_exclusive_under_concurrent_claims(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, job_id = await _seed_document(
            repository, status=DocumentStatus.QUEUED.value
        )

        results = await asyncio.gather(
            repository.claim_job(job_id, "worker-a", 300),
            repository.claim_job(job_id, "worker-b", 300),
        )

        assert sorted(results) == [False, True]
    finally:
        await database.dispose()


async def test_expired_lease_can_be_reclaimed(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        _, job_id = await _seed_document(repository, status=DocumentStatus.QUEUED.value)

        assert await repository.claim_job(job_id, "worker-a", lease_seconds=-1)
        # worker-a's lease is already in the past, so worker-b can reclaim the job -
        # this is what lets a hung/crashed worker's job recover instead of hanging forever.
        assert await repository.claim_job(job_id, "worker-b", lease_seconds=300)
    finally:
        await database.dispose()


async def test_renew_lease_fails_once_reclaimed_by_another_worker(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        _, job_id = await _seed_document(repository, status=DocumentStatus.QUEUED.value)

        assert await repository.claim_job(job_id, "worker-a", lease_seconds=-1)
        assert await repository.claim_job(job_id, "worker-b", lease_seconds=300)

        # worker-a no longer owns the lease (worker-b reclaimed it above), so its renewal
        # must fail rather than silently extending a lease it no longer holds.
        assert not await repository.renew_lease(job_id, "worker-a", 300)
        assert await repository.renew_lease(job_id, "worker-b", 300)
    finally:
        await database.dispose()


async def test_create_retry_job_rejects_second_concurrent_retry(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed_document(repository, status=DocumentStatus.FAILED.value)

        results = await asyncio.gather(
            repository.create_retry_job(document_id),
            repository.create_retry_job(document_id),
            return_exceptions=True,
        )

        successes = [item for item in results if isinstance(item, ProcessingJob)]
        failures = [item for item in results if isinstance(item, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)
    finally:
        await database.dispose()


async def test_update_job_raises_for_unknown_job(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        with pytest.raises(JobNotFoundError):
            await repository.update_job("missing-job", status=JobStatus.FAILED.value)
    finally:
        await database.dispose()


async def test_finish_processing_commits_document_and_job_together(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, job_id = await _seed_document(
            repository, status=DocumentStatus.TRANSLATING.value
        )

        await repository.finish_processing(
            document_id,
            job_id,
            document_values={"status": DocumentStatus.COMPLETED.value},
            job_values={"status": JobStatus.COMPLETED.value},
        )

        document = await repository.get(document_id)
        assert document.status == DocumentStatus.COMPLETED.value
    finally:
        await database.dispose()


async def test_financial_review_is_append_only_and_updates_document_summary(
    tmp_path: Path,
) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed_document(
            repository, status=DocumentStatus.NEEDS_REVIEW.value
        )
        await repository.update_document(
            document_id,
            financial_result_sha256="a" * 64,
        )
        reviewed_at = datetime.now(UTC)
        persisted = await repository.create_financial_review(
            FinancialReview(
                document_id=document_id,
                decision="approved",
                reviewer_subject="reviewer:tok-safe-fingerprint",
                note="Synthetic result checked.",
                corrections=[
                    {
                        "cell_id": "cell-1",
                        "normalized_value": "1234.56",
                        "currency": "EUR",
                        "reason": "Confirmed EU decimal format.",
                    }
                ],
                processing_version="prd-local-4",
                result_schema_version="financial-result-1.4",
                result_sha256="a" * 64,
                created_at=reviewed_at,
            )
        )

        document = await repository.get(document_id)
        history = await repository.financial_reviews(document_id)
        assert persisted.id == history[0].id
        assert history[0].corrections[0]["normalized_value"] == "1234.56"
        assert document.financial_review_status == "approved"
        assert document.financial_reviewed_by == "reviewer:tok-safe-fingerprint"
        # Financial approval must not hide an independent OCR/translation
        # review requirement on the document.
        assert document.status == DocumentStatus.NEEDS_REVIEW.value
    finally:
        await database.dispose()


async def test_reprocess_retry_resets_all_derived_document_counters(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        document_id, _ = await _seed_document(
            repository, status=DocumentStatus.NEEDS_REVIEW.value
        )
        await repository.update_document(
            document_id,
            pages_ready=12,
            translation_batches_done=3,
            translation_batches_total=3,
            financial_page_count=4,
            uncertain_page_count=1,
            financial_table_count=6,
            financial_issue_count=2,
            financial_result_sha256="b" * 64,
            financial_review_status="rejected",
            financial_reviewed_by="prior-reviewer",
            financial_reviewed_at=datetime.now(UTC),
            source_languages=["ar"],
        )

        await repository.create_retry_job(document_id, mode=RetryMode.REPROCESS)

        document = await repository.get(document_id)
        assert document.pages_ready == 0
        assert document.translation_batches_done is None
        assert document.translation_batches_total is None
        assert document.financial_page_count is None
        assert document.uncertain_page_count is None
        assert document.financial_table_count is None
        assert document.financial_issue_count is None
        assert document.financial_result_sha256 is None
        assert document.financial_review_status is None
        assert document.financial_reviewed_by is None
        assert document.financial_reviewed_at is None
        assert document.source_languages == []
        assert document.processing_version == "prd-local-4"
    finally:
        await database.dispose()
