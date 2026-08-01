import hashlib
from datetime import UTC, datetime

import structlog

from app.core.enums import DocumentStatus, JobStatus, TranslationStatus
from app.core.exceptions import AppError
from app.integrations.azure_openai.translator import AzureOpenAITranslator
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer
from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
from app.prompts.translation import TRANSLATION_PROMPT_VERSION
from app.repositories.documents import DocumentRepository
from app.schemas.page import CanonicalDocument, TableCell, TextBlock
from app.schemas.translation import (
    TranslationBatchRequest,
    TranslationBatchResponse,
    TranslationInput,
)
from app.services.export import ExportService
from app.services.language import LanguageService
from app.services.validation import TranslationValidator
from app.storage.local import LocalArtifactStorage

logger = structlog.get_logger(__name__)


class ProcessingService:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: LocalArtifactStorage,
        analyzer: DocumentIntelligenceAnalyzer,
        mapper: DocumentIntelligenceMapper,
        translator: AzureOpenAITranslator,
        language_service: LanguageService,
        validator: TranslationValidator,
        exporter: ExportService,
        *,
        max_batch_blocks: int,
        max_batch_chars: int,
        ocr_review_threshold: float,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.analyzer = analyzer
        self.mapper = mapper
        self.translator = translator
        self.language_service = language_service
        self.validator = validator
        self.exporter = exporter
        self.max_batch_blocks = max_batch_blocks
        self.max_batch_chars = max_batch_chars
        self.ocr_review_threshold = ocr_review_threshold

    async def _stage(self, document_id: str, status: DocumentStatus, progress: int) -> None:
        await self.repository.update_document(
            document_id,
            status=status.value,
            current_stage=status.value,
            progress_percent=progress,
            error_code=None,
            safe_error_message=None,
        )

    def _batches(self, blocks: list[TextBlock]) -> list[list[TextBlock]]:
        batches: list[list[TextBlock]] = []
        current: list[TextBlock] = []
        current_chars = 0
        for block in blocks:
            size = len(block.source_text)
            if current and (
                len(current) >= self.max_batch_blocks or current_chars + size > self.max_batch_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(block)
            current_chars += size
        if current:
            batches.append(current)
        return batches

    async def _translate(self, document: CanonicalDocument) -> bool:
        review_required = False
        targets = list(document.blocks)
        cell_targets: dict[str, TableCell] = {}
        for table in document.tables:
            for cell in table.cells:
                proxy = TextBlock(
                    block_id=cell.cell_id,
                    reading_order=len(targets) + 1,
                    source_text=cell.content,
                    source_language=cell.source_language,
                    bounding_regions=cell.bounding_regions,
                )
                targets.append(proxy)
                cell_targets[proxy.block_id] = cell

        translatable: list[TextBlock] = []
        for block in targets:
            block.source_language = self.language_service.detect(
                block.source_text, block.source_language
            )
            if not block.source_text.strip():
                block.translated_text = ""
                block.translation_status = TranslationStatus.NOT_REQUIRED
                continue
            if (
                block.ocr_confidence is not None
                and block.ocr_confidence < self.ocr_review_threshold
            ):
                block.review_required = True
                block.warnings.append(f"OCR confidence is below {self.ocr_review_threshold:.0%}.")
                review_required = True
            if self.language_service.should_translate(block.source_language):
                block.translation_status = TranslationStatus.PENDING
                translatable.append(block)
            elif block.source_language == "en":
                block.translated_text = block.source_text
                block.translation_status = TranslationStatus.NOT_REQUIRED
            else:
                block.translation_status = TranslationStatus.NEEDS_REVIEW
                block.review_required = True
                block.warnings.append("Language could not be confidently routed.")
                review_required = True

        for batch_index, blocks in enumerate(self._batches(translatable), start=1):
            inputs = [
                TranslationInput(
                    block_id=block.block_id,
                    source_language=block.source_language,
                    source_text=block.source_text,
                )
                for block in blocks
            ]
            request = TranslationBatchRequest(blocks=inputs)
            hash_input = f"{TRANSLATION_PROMPT_VERSION}\n{request.model_dump_json()}"
            input_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
            artifact = f"translations/batch-{batch_index:04d}.json"
            response: TranslationBatchResponse
            if self.storage.exists(document.document_id, artifact):
                cached = await self.storage.read_json(document.document_id, artifact)
                if cached.get("input_hash") == input_hash:
                    response = TranslationBatchResponse.model_validate(cached["response"])
                    self.validator.validate(inputs, response)
                else:
                    response = await self.translator.translate(request)
            else:
                response = await self.translator.translate(request)
            self.validator.validate(inputs, response)
            await self.storage.write_json(
                document.document_id,
                artifact,
                {
                    "input_hash": input_hash,
                    "prompt_version": TRANSLATION_PROMPT_VERSION,
                    "response": response.model_dump(mode="json"),
                },
            )
            translated_by_id = {
                item.block_id: item.translated_text for item in response.translations
            }
            for block in blocks:
                block.translated_text = translated_by_id[block.block_id]
                block.translation_status = TranslationStatus.TRANSLATED

        targets_by_id = {target.block_id: target for target in targets}
        for cell_id, cell in cell_targets.items():
            target = targets_by_id[cell_id]
            cell.source_language = target.source_language
            cell.translated_content = target.translated_text
            cell.translation_status = target.translation_status
            cell.review_required = target.review_required
            cell.warnings = list(target.warnings)
            review_required = review_required or target.review_required
        return review_required

    async def process(self, document_id: str) -> None:
        document_record = await self.repository.get(document_id)
        job = await self.repository.latest_job(document_id)
        await self.repository.update_job(
            job.id,
            status=JobStatus.RUNNING.value,
            started_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
        )
        try:
            await self._stage(document_id, DocumentStatus.EXTRACTING, 15)
            raw_path = "raw/document_intelligence.json"
            if self.storage.exists(document_id, raw_path):
                raw = await self.storage.read_json(document_id, raw_path)
            else:
                raw = await self.analyzer.analyze(
                    self.storage.source_path(document_id, document_record.stored_extension)
                )
                await self.storage.write_json(document_id, raw_path, raw)

            await self._stage(document_id, DocumentStatus.NORMALIZING, 35)
            canonical = self.mapper.map(
                raw,
                document_id=document_id,
                filename=document_record.original_filename,
            )
            language_inputs = [
                (block.source_text, block.source_language) for block in canonical.blocks
            ] + [
                (cell.content, cell.source_language)
                for table in canonical.tables
                for cell in table.cells
                if cell.content.strip()
            ]
            canonical.source_languages = sorted(
                {self.language_service.detect(text, hint) for text, hint in language_inputs}
            )
            await self.storage.write_json(
                document_id,
                "normalized/extracted.json",
                canonical.model_dump(mode="json"),
            )

            # Extraction is useful on its own. Persist page-level JSON before translation
            # so an unavailable OpenAI service never discards successful OCR output.
            extracted_pages = self.exporter.page_results(
                canonical,
                DocumentStatus.NORMALIZING.value,
            )
            for page in extracted_pages:
                await self.storage.write_json(
                    document_id,
                    f"pages/page-{page.page.page_number:04d}.json",
                    page.model_dump(mode="json"),
                )
            await self.repository.update_document(
                document_id,
                page_count=len(extracted_pages),
                source_languages=canonical.source_languages,
            )

            await self._stage(document_id, DocumentStatus.TRANSLATING, 55)
            review_required = await self._translate(canonical)
            await self._stage(document_id, DocumentStatus.VALIDATING, 80)
            final_status = (
                DocumentStatus.NEEDS_REVIEW if review_required else DocumentStatus.COMPLETED
            )
            canonical.status = final_status.value

            await self._stage(document_id, DocumentStatus.EXPORTING, 90)
            page_results = self.exporter.page_results(canonical, final_status.value)
            for page in page_results:
                await self.storage.write_json(
                    document_id,
                    f"pages/page-{page.page.page_number:04d}.json",
                    page.model_dump(mode="json"),
                )
            await self.storage.write_json(
                document_id,
                "exports/extracted-document.json",
                await self.storage.read_json(document_id, "normalized/extracted.json"),
            )
            await self.storage.write_json(
                document_id,
                "exports/bilingual-document.json",
                canonical.model_dump(mode="json"),
            )
            await self.storage.write_json(
                document_id,
                "manifest.json",
                {
                    "schema_version": "1.0",
                    "document_id": document_id,
                    "page_count": len(page_results),
                    "artifacts": [
                        "raw/document_intelligence.json",
                        "normalized/extracted.json",
                        "exports/extracted-document.json",
                        "exports/bilingual-document.json",
                    ],
                },
            )
            await self.repository.update_document(
                document_id,
                status=final_status.value,
                current_stage=final_status.value,
                progress_percent=100,
                page_count=len(page_results),
                source_languages=canonical.source_languages,
                completed_at=datetime.now(UTC),
            )
            await self.repository.update_job(
                job.id,
                status=JobStatus.COMPLETED.value,
                stage="completed",
                completed_at=datetime.now(UTC),
            )
        except AppError as exc:
            await self.repository.update_document(
                document_id,
                status=DocumentStatus.FAILED.value,
                current_stage=DocumentStatus.FAILED.value,
                error_code=exc.code,
                safe_error_message=exc.message,
            )
            await self.repository.update_job(
                job.id,
                status=JobStatus.FAILED.value,
                error_code=exc.code,
                safe_error_message=exc.message,
                completed_at=datetime.now(UTC),
            )
            await logger.awarning(
                "document_processing_failed",
                document_id=document_id,
                error_code=exc.code,
                retryable=getattr(exc, "retryable", False),
            )
        except Exception:
            await self.repository.update_document(
                document_id,
                status=DocumentStatus.FAILED.value,
                current_stage=DocumentStatus.FAILED.value,
                error_code="processing_failed",
                safe_error_message="Document processing failed unexpectedly.",
            )
            await self.repository.update_job(
                job.id,
                status=JobStatus.FAILED.value,
                error_code="processing_failed",
                safe_error_message="Document processing failed unexpectedly.",
                completed_at=datetime.now(UTC),
            )
            await logger.aexception(
                "document_processing_failed_unexpectedly",
                document_id=document_id,
            )
