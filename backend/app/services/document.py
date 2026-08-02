import hashlib
import re
from pathlib import Path
from uuid import uuid4

import aiofiles
import structlog
from fastapi import UploadFile

from app.core.config import Settings
from app.core.enums import TERMINAL_DOCUMENT_STATUSES, DocumentStatus, RetryMode
from app.core.exceptions import ConflictError, InvalidDocumentError
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.repositories.documents import DocumentRepository
from app.services.security_gateway import SecurityGateway
from app.services.upload_security import assert_pdf_safe
from app.storage.local import LocalArtifactStorage

logger = structlog.get_logger(__name__)

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        storage: LocalArtifactStorage,
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
            assert_pdf_safe(final_path, max_pages=self.settings.max_document_pages)
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
        job = await self.repository.create_retry_job(document_id, mode=mode)
        if mode == RetryMode.REPROCESS:
            for relative in (
                "raw/document_intelligence.json",
                "normalized/extracted.json",
            ):
                path = self.storage.artifact_path(document_id, relative)
                path.unlink(missing_ok=True)
            translations = self.storage.document_dir(document_id) / "translations"
            if translations.exists():
                for item in translations.glob("*.json"):
                    item.unlink(missing_ok=True)
        elif mode == RetryMode.RETRANSLATE:
            translations = self.storage.document_dir(document_id) / "translations"
            if translations.exists():
                for item in translations.glob("*.json"):
                    item.unlink(missing_ok=True)
        return job

    async def delete(self, document_id: str) -> None:
        document = await self.repository.get(document_id)
        if DocumentStatus(document.status) not in TERMINAL_DOCUMENT_STATUSES:
            raise ConflictError("A document cannot be deleted while it is processing.")
        await self.repository.delete(document_id)
        try:
            await self.storage.delete_document(document_id)
        except OSError:
            await logger.aexception(
                "document_storage_cleanup_failed",
                document_id=document_id,
            )
