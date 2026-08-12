import asyncio
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiofiles
import structlog
from fastapi import UploadFile

from app.core.config import Settings
from app.core.enums import (
    RETRIABLE_DOCUMENT_STATUSES,
    TERMINAL_DOCUMENT_STATUSES,
    DocumentStatus,
    RetryMode,
)
from app.core.exceptions import ConflictError, InvalidDocumentError
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.repositories.documents import DocumentRepository
from app.services.security_gateway import SecurityGateway
from app.services.upload_security import assert_pdf_safe
from app.storage.base import ArtifactStorage

logger = structlog.get_logger(__name__)

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        storage: ArtifactStorage,
        gateway: SecurityGateway | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.storage = storage
        self.gateway = gateway or SecurityGateway(settings)

    @staticmethod
    def _detect_type(header: bytes) -> tuple[str, str] | None:
        if header.startswith(b"%PDF-"):
            return "pdf", "application/pdf"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png", "image/png"
        if header.startswith(b"\xff\xd8\xff"):
            return "jpg", "image/jpeg"
        if header.startswith((b"II*\x00", b"MM\x00*")):
            return "tiff", "image/tiff"
        if header.startswith(b"BM"):
            return "bmp", "image/bmp"
        return None

    async def create_upload(
        self,
        upload: UploadFile,
        *,
        data_class: str | None = None,
        processing_profile: str | None = None,
        owner_subject: str = "local-api-token",
        organization_id: str = "org-local",
    ) -> Document:
        original_name = Path(upload.filename or "document").name
        original_name = SAFE_FILENAME_RE.sub("_", original_name)[:255]
        extension = Path(original_name).suffix.lower().lstrip(".")
        if extension not in self.settings.extension_set:
            raise InvalidDocumentError("File extension is not allowed.")

        classified = data_class or self.settings.default_data_class
        profile = self.gateway.select_profile(
            data_class=classified,
            requested_profile=processing_profile,
        )

        document_id = str(uuid4())
        self.storage.ensure_document_dirs(document_id)
        temporary = self.storage.document_dir(document_id) / "source" / ".upload.tmp"
        digest = hashlib.sha256()
        size = 0
        first_bytes = b""
        limit = self.settings.max_upload_size_mb * 1024 * 1024
        final_path: Path | None = None
        try:
            async with aiofiles.open(temporary, "wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    if not first_bytes:
                        first_bytes = chunk[:16]
                    size += len(chunk)
                    if size > limit:
                        raise InvalidDocumentError(
                            f"File exceeds the {self.settings.max_upload_size_mb} MB limit."
                        )
                    digest.update(chunk)
                    await handle.write(chunk)
            detected = self._detect_type(first_bytes)
            if detected is None:
                raise InvalidDocumentError(
                    "The file signature is not an allowed type (PDF, PNG, JPEG, TIFF, or BMP)."
                )
            detected_extension, content_type = detected
            if extension == "jpeg":
                extension = "jpg"
            if extension == "tif":
                extension = "tiff"
            if extension != detected_extension:
                raise InvalidDocumentError("File extension does not match its content.")
            final_path = self.storage.source_path(document_id, detected_extension)
            temporary.replace(final_path)
            # pypdf's page-tree walk is synchronous CPU-bound work; this app runs its
            # background job workers as asyncio tasks on the same event loop as the
            # HTTP server (see InProcessJobRunner), so an un-threaded parse here would
            # stall every other concurrent request for its full duration.
            page_estimate = await asyncio.to_thread(
                assert_pdf_safe, final_path, max_pages=self.settings.max_document_pages
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            await self.storage.delete_document(document_id)
            raise
        finally:
            await upload.close()

        document = Document(
            id=document_id,
            original_filename=original_name,
            stored_extension=detected_extension,
            content_type=content_type,
            file_size=size,
            sha256=digest.hexdigest(),
            status=DocumentStatus.QUEUED.value,
            current_stage="queued",
            target_language=self.settings.target_language,
            data_class=classified,
            processing_profile=profile.value,
            financial_extraction_mode=self.settings.financial_extraction_mode,
            page_count=page_estimate,
            organization_id=organization_id,
            owner_subject=owner_subject,
            assignment_status="unassigned",
            document_review_status="draft",
        )
        job = ProcessingJob(document_id=document_id)
        try:
            return await self.repository.create(document, job)
        except Exception:
            # DB insert failed after the source landed on disk — remove orphans.
            await self.storage.delete_document(document_id)
            raise

    async def retry(
        self,
        document_id: str,
        *,
        mode: RetryMode = RetryMode.RESUME,
    ) -> ProcessingJob:
        document = await self.repository.get(document_id)
        if getattr(document, "financial_review_status", None) == "approved":
            raise ConflictError(
                "Approved financial results cannot be overwritten by retry."
            )
        if getattr(document, "translation_review_status", None) == "approved":
            raise ConflictError(
                "Approved translation results cannot be overwritten by retry."
            )
        if getattr(document, "document_review_status", None) == "approved":
            raise ConflictError(
                "Approved documents cannot be overwritten by retry."
            )
        if mode == RetryMode.REPROCESS:
            # Best-effort pre-check so cleanup never destroys artifacts of a
            # document that could not be retried anyway. The atomic status guard
            # remains inside create_retry_job.
            if DocumentStatus(document.status) not in RETRIABLE_DOCUMENT_STATUSES:
                raise ConflictError(
                    "Only failed, cancelled, or reviewable documents can be retried."
                )
            # Artifact invalidation must complete BEFORE the retry job exists.
            # Otherwise the recovery sweeper can claim the queued job mid-cleanup
            # and resume from stale normalized/extracted artifacts.
            try:
                # Invalidate the completion marker before touching any derived file.
                # Readers can then fail closed even if cleanup is interrupted midway.
                await self.storage.delete_artifact(document_id, "manifest.json")
                for prefix in (
                    "pages",
                    "exports",
                    "raw",
                    "normalized",
                    "classification",
                    "validation",
                    "translations",
                    "processing",
                ):
                    await self.storage.delete_prefix(document_id, prefix)
            except Exception:
                # No retry job was created yet, so there is no orphan queued job.
                now = datetime.now(UTC)
                await self.repository.update_document(
                    document_id,
                    status=DocumentStatus.FAILED.value,
                    current_stage=DocumentStatus.FAILED.value,
                    error_code="reprocess_cleanup_failed",
                    safe_error_message="Derived artifacts could not be invalidated safely.",
                    completed_at=now,
                )
                raise
        elif mode == RetryMode.RETRANSLATE:
            await self.storage.delete_prefix(document_id, "translations")
        return await self.repository.create_retry_job(document_id, mode=mode)

    async def cancel(self, document_id: str) -> Document:
        return await self.repository.cancel_document(document_id)

    async def delete(self, document_id: str) -> None:
        document = await self.repository.get(document_id)
        if DocumentStatus(document.status) not in TERMINAL_DOCUMENT_STATUSES:
            raise ConflictError("A document cannot be deleted while it is processing.")
        try:
            await self.storage.delete_document(document_id)
        except OSError:
            await logger.aexception(
                "document_storage_cleanup_failed",
                document_id=document_id,
            )
            # Preserve the database record so deletion can be retried and the
            # remaining artifact is not orphaned without an owner or policy.
            raise
        await self.repository.delete(document_id)
