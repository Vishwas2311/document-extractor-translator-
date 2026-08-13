import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.core.config import Settings
from app.core.enums import RetryMode
from app.core.exceptions import ConflictError, InvalidDocumentError
from app.services.document import DocumentService
from app.storage.local import LocalArtifactStorage


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"%PDF-1.7", ("pdf", "application/pdf")),
        (b"\x89PNG\r\n\x1a\n", ("png", "image/png")),
        (b"\xff\xd8\xff\xe0", ("jpg", "image/jpeg")),
        (b"II*\x00", ("tiff", "image/tiff")),
        (b"MM\x00*", ("tiff", "image/tiff")),
        (b"BM1234", ("bmp", "image/bmp")),
    ],
)
def test_detects_allowed_file_signatures(header: bytes, expected: tuple[str, str]) -> None:
    assert DocumentService._detect_type(header) == expected


def test_rejects_unknown_file_signature() -> None:
    assert DocumentService._detect_type(b"not-a-document") is None


async def test_create_upload_rejects_a_real_oversized_file_via_streaming_check(
    tmp_path: Path,
) -> None:
    """Confirms the *actual* streaming per-chunk check in `create_upload` rejects an
    oversized file before it's ever fully buffered - not just that the final-size
    arithmetic would work out in theory."""
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    settings = Settings(auth_required=False, max_upload_size_mb=1)
    service = DocumentService(settings, repository=None, storage=storage)  # type: ignore[arg-type]

    oversized_payload = b"%PDF-1.7" + (b"\x00" * (2 * 1024 * 1024))  # ~2 MB > 1 MB limit
    upload = UploadFile(filename="big.pdf", file=io.BytesIO(oversized_payload))

    with pytest.raises(InvalidDocumentError, match="1 MB limit"):
        await service.create_upload(upload)

    # The partial temp file and document directory must not be left behind.
    assert not any(storage.root.rglob("*"))


class RetryRepository:
    def __init__(
        self,
        *,
        review_status: str | None = None,
        status: str = "failed",
    ) -> None:
        self.review_status = review_status
        self.status = status
        self.created_jobs = 0
        self.finished: list[dict[str, object]] = []
        self.document_updates: list[dict[str, object]] = []

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            status=self.status,
            financial_review_status=self.review_status,
        )

    async def create_retry_job(
        self, document_id: str, *, mode: RetryMode
    ) -> SimpleNamespace:
        self.created_jobs += 1
        return SimpleNamespace(id=f"job-{self.created_jobs}")

    async def update_document(self, document_id: str, **values: object) -> None:
        self.document_updates.append({"document_id": document_id, **values})

    async def mark_retriable_document_failed(
        self,
        document_id: str,
        *,
        error_code: str,
        safe_error_message: str,
        completed_at: object,
    ) -> bool:
        if self.status not in {"failed", "needs_review", "cancelled"}:
            return False
        self.status = "failed"
        self.document_updates.append(
            {
                "document_id": document_id,
                "status": "failed",
                "current_stage": "failed",
                "error_code": error_code,
                "safe_error_message": safe_error_message,
                "completed_at": completed_at,
            }
        )
        return True

    async def finish_processing(
        self,
        document_id: str,
        job_id: str,
        *,
        document_values: dict[str, object],
        job_values: dict[str, object],
    ) -> None:
        self.finished.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "document_values": document_values,
                "job_values": job_values,
            }
        )


async def test_reprocess_removes_every_derived_artifact_but_preserves_source(
    tmp_path: Path,
) -> None:
    document_id = "doc-reprocess"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    source = storage.source_path(document_id, "pdf")
    source.write_bytes(b"%PDF-1.7 synthetic")
    stale_artifacts = (
        "raw/range-0001.json",
        "normalized/extracted.json",
        "classification/pages.json",
        "validation/financial.json",
        "pages/page-0001.json",
        "pages/index.json",
        "translations/batch-0001.json",
        "exports/financial-document.json",
        "exports/financial-document.csv",
        "exports/financial-document.xlsx",
        "manifest.json",
    )
    for relative_path in stale_artifacts:
        if relative_path.endswith(".json"):
            await storage.write_json(document_id, relative_path, {"stale": True})
        elif relative_path.endswith(".xlsx"):
            await storage.write_bytes(document_id, relative_path, b"stale")
        else:
            await storage.write_text(document_id, relative_path, "stale")

    repository = RetryRepository()
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        storage,
    )

    await service.retry(document_id, mode=RetryMode.REPROCESS)

    assert source.read_bytes() == b"%PDF-1.7 synthetic"
    assert not any(storage.exists(document_id, path) for path in stale_artifacts)
    assert repository.created_jobs == 1
    assert repository.finished == []


async def test_reprocess_invalidates_artifacts_before_the_retry_job_exists(
    tmp_path: Path,
) -> None:
    """The recovery sweeper can claim a queued job the moment it exists, so the
    stale manifest/derived artifacts must already be gone by the time
    create_retry_job runs - otherwise a worker can resume from stale
    normalized/extracted.json mid-cleanup."""
    document_id = "doc-reprocess-order"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    await storage.write_json(document_id, "manifest.json", {"stale": True})
    await storage.write_json(document_id, "normalized/extracted.json", {"stale": True})

    class OrderingRepository(RetryRepository):
        def __init__(self) -> None:
            super().__init__(status="needs_review")
            self.artifacts_present_at_job_creation: list[str] = []

        async def create_retry_job(
            self, document_id: str, *, mode: RetryMode
        ) -> SimpleNamespace:
            self.artifacts_present_at_job_creation = [
                path
                for path in ("manifest.json", "normalized/extracted.json")
                if storage.exists(document_id, path)
            ]
            return await super().create_retry_job(document_id, mode=mode)

    repository = OrderingRepository()
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        storage,
    )

    await service.retry(document_id, mode=RetryMode.REPROCESS)

    assert repository.created_jobs == 1
    # Artifacts were already invalidated when the job became claimable.
    assert repository.artifacts_present_at_job_creation == []


async def test_reprocess_cleanup_failure_marks_document_failed_without_a_queued_job(
    tmp_path: Path,
) -> None:
    document_id = "doc-cleanup-fail"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)

    class FailingCleanupStorage:
        def __getattr__(self, name: str) -> object:
            return getattr(storage, name)

        async def delete_artifact(self, document_id: str, relative_path: str) -> None:
            raise OSError("simulated cleanup failure")

    repository = RetryRepository(status="failed")
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        FailingCleanupStorage(),  # type: ignore[arg-type]
    )

    with pytest.raises(OSError, match="simulated cleanup failure"):
        await service.retry(document_id, mode=RetryMode.REPROCESS)

    # No orphan queued job exists, and the document records the failure.
    assert repository.created_jobs == 0
    assert repository.document_updates
    failure = repository.document_updates[-1]
    assert failure["status"] == "failed"
    assert failure["error_code"] == "reprocess_cleanup_failed"


async def test_concurrent_reprocess_calls_do_not_race_cleanup(tmp_path: Path) -> None:
    """Regression: two overlapping reprocess requests used to race
    shutil.rmtree against each other with no lock, and a losing request's
    failure handler could stomp a document a winning request already moved
    past retriable. The per-document lock must fully serialize cleanup, and
    the loser must see the winner's status change and cleanly conflict
    instead of re-running cleanup or overwriting the winner's progress."""
    document_id = "doc-concurrent-reprocess"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    await storage.write_json(document_id, "manifest.json", {"stale": True})

    concurrent_count = 0
    max_concurrent = 0

    class SlowCleanupStorage:
        def __getattr__(self, name: str) -> object:
            return getattr(storage, name)

        async def delete_artifact(self, document_id: str, relative_path: str) -> None:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            await storage.delete_artifact(document_id, relative_path)

    class StatusAdvancingRepository(RetryRepository):
        async def create_retry_job(
            self, document_id: str, *, mode: RetryMode
        ) -> SimpleNamespace:
            # Mirror the real repository: a successful create_retry_job moves
            # the document out of the retriable set.
            self.status = "queued"
            return await super().create_retry_job(document_id, mode=mode)

    repository = StatusAdvancingRepository(status="failed")
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        SlowCleanupStorage(),  # type: ignore[arg-type]
    )

    results = await asyncio.gather(
        service.retry(document_id, mode=RetryMode.REPROCESS),
        service.retry(document_id, mode=RetryMode.REPROCESS),
        return_exceptions=True,
    )

    # The lock must have prevented both cleanups from running at once.
    assert max_concurrent == 1
    successes = [r for r in results if not isinstance(r, BaseException)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    # Only the winner's job was created; the loser never re-ran cleanup or
    # overwrote the winner's now-queued status.
    assert repository.created_jobs == 1
    assert repository.status == "queued"


async def test_reprocess_refuses_a_document_that_is_still_processing(
    tmp_path: Path,
) -> None:
    document_id = "doc-still-processing"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    await storage.write_json(document_id, "manifest.json", {"current": True})
    repository = RetryRepository(status="translating")
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        storage,
    )

    with pytest.raises(ConflictError, match="can be retried"):
        await service.retry(document_id, mode=RetryMode.REPROCESS)

    # The active document's artifacts were not touched.
    assert storage.exists(document_id, "manifest.json")
    assert repository.created_jobs == 0


@pytest.mark.parametrize("mode", list(RetryMode))
async def test_retry_cannot_overwrite_an_approved_financial_result(
    tmp_path: Path,
    mode: RetryMode,
) -> None:
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    repository = RetryRepository(review_status="approved")
    service = DocumentService(
        Settings(auth_required=False),
        repository,  # type: ignore[arg-type]
        storage,
    )

    with pytest.raises(ConflictError, match="cannot be overwritten"):
        await service.retry("doc-approved", mode=mode)

    assert repository.created_jobs == 0
