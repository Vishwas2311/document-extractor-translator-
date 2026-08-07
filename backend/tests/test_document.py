from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.enums import RetryMode
from app.core.exceptions import ConflictError
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


class RetryRepository:
    def __init__(self, *, review_status: str | None = None) -> None:
        self.review_status = review_status
        self.created_jobs = 0
        self.finished: list[dict[str, object]] = []

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            financial_review_status=self.review_status,
        )

    async def create_retry_job(
        self, document_id: str, *, mode: RetryMode
    ) -> SimpleNamespace:
        self.created_jobs += 1
        return SimpleNamespace(id=f"job-{self.created_jobs}")

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
