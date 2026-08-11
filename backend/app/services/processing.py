import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from app.core.enums import DocumentStatus, JobStatus, ProcessingProfile, TranslationStatus
from app.core.exceptions import (
    AppError,
    AzureServiceError,
    JobCancelledError,
    JobLeaseLostError,
    JobSupersededError,
    PolicyBlockedError,
    TranslationValidationError,
)
from app.core.versioning import CURRENT_PROCESSING_VERSION
from app.integrations.azure_openai.translator import AzureOpenAITranslator
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer
from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
from app.prompts.translation import TRANSLATION_PROMPT_VERSION
from app.repositories.documents import DocumentRepository
from app.schemas.financial import FinancialClassificationResult, FinancialResult
from app.schemas.page import CanonicalDocument, TableCell, TextBlock
from app.schemas.translation import (
    TranslationBatchRequest,
    TranslationBatchResponse,
    TranslationInput,
)
from app.services.di_ranges import (
    assign_stable_ids,
    format_pages_param,
    merge_canonical_parts,
    page_ranges,
    range_artifact_path,
)
from app.services.export import ExportService
from app.services.financial import (
    FinancialCandidateSelector,
    FinancialExtractionService,
    financial_result_csv,
    financial_result_sha256,
    financial_result_xlsx,
    selected_page_ranges,
)
from app.services.language import LanguageService
from app.services.pdf_chunks import (
    chunk_pdf_path,
    remap_di_page_numbers,
    write_pdf_page_chunk,
)
from app.services.security_gateway import SecurityGateway
from app.services.table_integrity import TableIntegrityService
from app.services.upload_security import assert_pdf_safe
from app.services.validation import TranslationValidator
from app.storage.base import ArtifactStorage

logger = structlog.get_logger(__name__)

PAGES_INDEX_PATH = "pages/index.json"
FINANCIAL_CLASSIFICATION_PATH = "classification/pages.json"
FINANCIAL_RESULT_PATH = "normalized/financial.json"
FINANCIAL_VALIDATION_PATH = "validation/financial.json"
TABLE_RECONCILIATION_PATH = "normalized/table-reconciliation.json"
ProgressCallback = Callable[[int, int], Awaitable[None]]
BatchCompleteCallback = Callable[[list[TextBlock]], Awaitable[None]]



class ProcessingService:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: ArtifactStorage,
        analyzer: DocumentIntelligenceAnalyzer,
        mapper: DocumentIntelligenceMapper,
        translator: AzureOpenAITranslator,
        language_service: LanguageService,
        validator: TranslationValidator,
        exporter: ExportService,
        gateway: SecurityGateway,
        *,
        max_batch_blocks: int,
        max_batch_chars: int,
        ocr_review_threshold: float,
        worker_id: str,
        job_lease_seconds: int,
        job_heartbeat_seconds: int = 30,
        di_page_range_size: int = 25,
        max_document_pages: int = 300,
        translation_concurrency: int = 8,
        di_range_concurrency: int = 2,
        di_use_physical_chunks: bool = True,
        di_dense_page_threshold: float = 0.65,
        translation_dedupe_identical: bool = True,
        translation_progress_flush_every: int = 4,
        financial_selector: FinancialCandidateSelector | None = None,
        financial_extractor: FinancialExtractionService | None = None,
        table_integrity: TableIntegrityService | None = None,
        financial_extraction_mode: str = "off",
        financial_classifier_model_id: str | None = None,
        financial_classifier_version: str = "1.0",
        financial_classifier_split_mode: str = "perPage",
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.analyzer = analyzer
        self.mapper = mapper
        self.translator = translator
        self.language_service = language_service
        self.validator = validator
        self.exporter = exporter
        self.gateway = gateway
        self.max_batch_blocks = max_batch_blocks
        self.max_batch_chars = max_batch_chars
        self.translation_concurrency = max(1, translation_concurrency)
        self.di_range_concurrency = max(1, di_range_concurrency)
        self.di_use_physical_chunks = di_use_physical_chunks
        self.di_dense_page_threshold = di_dense_page_threshold
        self.translation_dedupe_identical = translation_dedupe_identical
        self.translation_progress_flush_every = max(1, translation_progress_flush_every)
        self.ocr_review_threshold = ocr_review_threshold
        self.worker_id = worker_id
        self.job_lease_seconds = job_lease_seconds
        self.job_heartbeat_seconds = max(5, job_heartbeat_seconds)
        self.di_page_range_size = max(1, di_page_range_size)
        self.max_document_pages = max_document_pages
        self.financial_selector = financial_selector
        self.financial_extractor = financial_extractor
        self.table_integrity = table_integrity or TableIntegrityService()
        self.financial_extraction_mode = financial_extraction_mode
        self.financial_classifier_model_id = financial_classifier_model_id
        self.financial_classifier_version = financial_classifier_version
        self.financial_classifier_split_mode = financial_classifier_split_mode

    async def _stage(
        self, document_id: str, job_id: str, status: DocumentStatus, progress: int
    ) -> None:
        await self._assert_job_alive(document_id, job_id)
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            status=status.value,
            current_stage=status.value,
            progress_percent=progress,
            error_code=None,
            safe_error_message=None,
        )
        await self.repository.update_active_job(job_id, stage=status.value)
        renewed = await self.repository.renew_lease(job_id, self.worker_id, self.job_lease_seconds)
        if not renewed:
            await self._assert_job_alive(document_id, job_id)
            raise JobLeaseLostError(
                "This worker's job lease expired and was reclaimed by another worker."
            )

    async def _assert_job_alive(self, document_id: str, job_id: str) -> None:
        await self.repository.assert_job_is_current(document_id, job_id)

    async def _heartbeat_loop(self, job_id: str, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.job_heartbeat_seconds)
                return
            except TimeoutError:
                try:
                    renewed = await self.repository.renew_lease(
                        job_id, self.worker_id, self.job_lease_seconds
                    )
                    if not renewed:
                        stop.set()
                        return
                except Exception:
                    # Transient DB errors must not kill the processing loop.
                    await logger.aexception("heartbeat_renew_failed", job_id=job_id)

    async def _mark_pages_failed(self, document_id: str, page_numbers: list[int]) -> None:
        for number in page_numbers:
            relative = f"pages/page-{number:04d}.json"
            if not self.storage.exists(document_id, relative):
                continue
            payload = await self.storage.read_json(document_id, relative)
            payload["document_status"] = DocumentStatus.FAILED.value
            await self.storage.write_json(document_id, relative, payload)

    @staticmethod
    def _pages_touched(blocks: list[TextBlock]) -> set[int]:
        pages: set[int] = set()
        for block in blocks:
            for region in block.bounding_regions:
                pages.add(region.page_number)
        return pages

    @staticmethod
    def _observed_page_count(page_numbers: list[int]) -> int:
        return max(page_numbers) if page_numbers else 0

    async def _merge_pages_index(
        self,
        document_id: str,
        page_results: list[Any],
    ) -> None:
        index: dict[str, Any] = {"pages": []}
        if self.storage.exists(document_id, PAGES_INDEX_PATH):
            index = await self.storage.read_json(document_id, PAGES_INDEX_PATH)
        by_number = {
            int(item["page_number"]): item
            for item in index.get("pages", [])
            if isinstance(item, dict) and "page_number" in item
        }
        for page in page_results:
            existing = by_number.get(page.page.page_number, {})
            by_number[page.page.page_number] = {
                **existing,
                "page_number": page.page.page_number,
                "width": page.page.width,
                "height": page.page.height,
                "unit": page.page.unit,
                "angle": page.page.angle,
                "block_count": len(page.blocks),
                "table_count": len(page.tables),
                "review_required": bool(page.warnings)
                or any(block.review_required for block in page.blocks)
                or any(
                    cell.review_required for table in page.tables for cell in table.cells
                ),
            }
        index["pages"] = [by_number[number] for number in sorted(by_number)]
        await self.storage.write_json(document_id, PAGES_INDEX_PATH, index)

    async def _write_pages(
        self,
        document_id: str,
        canonical: CanonicalDocument,
        status_value: str,
        *,
        only_pages: set[int] | None = None,
    ) -> list[int]:
        page_results = self.exporter.page_results(
            canonical, status_value, only_pages=only_pages
        )
        page_numbers = [page.page.page_number for page in page_results]
        for page in page_results:
            await self.storage.write_json(
                document_id,
                f"pages/page-{page.page.page_number:04d}.json",
                page.model_dump(mode="json"),
            )
        if page_results:
            await self._merge_pages_index(document_id, page_results)
        return page_numbers

    async def _write_financial_classification(
        self,
        document_id: str,
        classification: FinancialClassificationResult,
    ) -> None:
        await self.storage.write_json(
            document_id,
            FINANCIAL_CLASSIFICATION_PATH,
            classification.model_dump(mode="json"),
        )
        index: dict[str, Any] = {"pages": []}
        if self.storage.exists(document_id, PAGES_INDEX_PATH):
            index = await self.storage.read_json(document_id, PAGES_INDEX_PATH)
        existing = {
            int(item["page_number"]): item
            for item in index.get("pages", [])
            if isinstance(item, dict) and "page_number" in item
        }
        for page in classification.pages:
            current = existing.get(page.page_number, {})
            existing[page.page_number] = {
                "page_number": page.page_number,
                "width": float(current.get("width", 0)),
                "height": float(current.get("height", 0)),
                "unit": str(current.get("unit", "pixel")),
                "angle": float(current.get("angle", 0)),
                "block_count": int(current.get("block_count", 0)),
                "table_count": int(current.get("table_count", 0)),
                "review_required": bool(current.get("review_required", False))
                or page.review_required,
                "financial_label": page.label,
                "financial_confidence": page.confidence,
                "financial_disposition": page.disposition.value,
                "financial_selected": page.selected,
                "financial_reason": page.reasons,
                "financial_table_count": int(current.get("financial_table_count", 0)),
                "validation_issue_count": int(current.get("validation_issue_count", 0)),
            }
        index["pages"] = [existing[number] for number in sorted(existing)]
        await self.storage.write_json(document_id, PAGES_INDEX_PATH, index)

    async def _classify_financial_pages(
        self,
        document_id: str,
        document_record: Any,
        job_id: str,
    ) -> FinancialClassificationResult | None:
        stored_mode = str(
            getattr(
                document_record,
                "financial_extraction_mode",
                self.financial_extraction_mode,
            )
        )
        if stored_mode != "selective":
            return None
        if self.financial_selector is None or not self.financial_classifier_model_id:
            raise PolicyBlockedError(
                "Selective financial extraction is not configured with an approved classifier."
            )
        if self.storage.exists(document_id, FINANCIAL_CLASSIFICATION_PATH):
            try:
                cached = FinancialClassificationResult.model_validate(
                    await self.storage.read_json(document_id, FINANCIAL_CLASSIFICATION_PATH)
                )
            except (OSError, ValueError, ValidationError) as exc:
                raise PolicyBlockedError(
                    "The cached financial classification is invalid. Reprocess the document."
                ) from exc
            if (
                cached.classifier_id != self.financial_classifier_model_id
                or cached.classifier_version != self.financial_classifier_version
                or (
                    self.financial_selector is not None
                    and cached.selection_policy_fingerprint
                    != self.financial_selector.policy_fingerprint
                )
            ):
                raise PolicyBlockedError(
                    "The cached financial classification does not match the active "
                    "classifier version. Reprocess the document."
                )
            return cached

        source_page_count = int(getattr(document_record, "page_count", 0) or 0)
        if source_page_count < 1:
            source_path = self.storage.source_path(
                document_id, document_record.stored_extension
            )
            source_page_count = await self._estimate_pdf_pages(source_path) or 1
        await self._stage(document_id, job_id, DocumentStatus.CLASSIFYING, 8)
        source_path = self.storage.source_path(document_id, document_record.stored_extension)
        raw = await self.analyzer.classify(
            source_path,
            classifier_id=self.financial_classifier_model_id,
            split_mode=self.financial_classifier_split_mode,
        )
        await self._assert_job_alive(document_id, job_id)
        classification = self.financial_selector.from_provider(
            document_id=document_id,
            classifier_id=self.financial_classifier_model_id,
            classifier_version=self.financial_classifier_version,
            source_page_count=source_page_count,
            raw=raw,
        )
        await self._write_financial_classification(document_id, classification)
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            financial_page_count=len(classification.selected_pages),
            uncertain_page_count=sum(
                page.review_required for page in classification.pages if page.selected
            ),
        )
        return classification

    async def _classify_from_layout(
        self,
        document_id: str,
        document: CanonicalDocument,
        document_record: Any,
        job_id: str,
    ) -> FinancialClassificationResult | None:
        stored_mode = str(
            getattr(
                document_record,
                "financial_extraction_mode",
                self.financial_extraction_mode,
            )
        )
        if stored_mode != "post_extract":
            return None
        if self.financial_selector is None:
            raise PolicyBlockedError("Financial page selection is not configured.")
        source_page_count = int(
            getattr(document_record, "page_count", 0) or len(document.pages) or 1
        )
        classification = self.financial_selector.from_layout(
            document=document,
            source_page_count=source_page_count,
        )
        await self._write_financial_classification(document_id, classification)
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            financial_page_count=len(classification.selected_pages),
            uncertain_page_count=sum(
                page.review_required for page in classification.pages if page.selected
            ),
        )
        return classification

    @staticmethod
    def _translation_view(
        document: CanonicalDocument,
        selected_pages: set[int] | None,
    ) -> CanonicalDocument:
        if selected_pages is None:
            return document
        blocks = [
            block
            for block in document.blocks
            if any(region.page_number in selected_pages for region in block.bounding_regions)
        ]
        tables = [
            table
            for table in document.tables
            if any(
                region.page_number in selected_pages
                for cell in table.cells
                for region in cell.bounding_regions
            )
        ]
        pages = [page for page in document.pages if page.page_number in selected_pages]
        return document.model_copy(update={"blocks": blocks, "tables": tables, "pages": pages})

    async def _write_financial_result(
        self,
        document_id: str,
        document: CanonicalDocument,
        classification: FinancialClassificationResult,
        processing_version: str,
    ) -> FinancialResult:
        if self.financial_extractor is None:
            raise PolicyBlockedError("Financial extraction is not configured.")
        result = self.financial_extractor.build(
            document,
            classification,
            processing_version=processing_version,
        )
        await self.storage.write_json(
            document_id, FINANCIAL_RESULT_PATH, result.model_dump(mode="json")
        )
        await self.storage.write_json(
            document_id,
            FINANCIAL_VALIDATION_PATH,
            result.validation.model_dump(mode="json"),
        )
        await self.storage.write_text(
            document_id,
            "exports/financial-document.csv",
            financial_result_csv(result),
        )
        await self.storage.write_bytes(
            document_id,
            "exports/financial-document.xlsx",
            financial_result_xlsx(result),
        )
        index = await self.storage.read_json(document_id, PAGES_INDEX_PATH)
        table_counts: dict[int, int] = {}
        for table in result.tables:
            for page_number in table.source_pages:
                table_counts[page_number] = table_counts.get(page_number, 0) + 1
        issue_counts: dict[int, int] = {}
        for issue in result.validation.issues:
            if issue.page_number is not None:
                issue_counts[issue.page_number] = issue_counts.get(issue.page_number, 0) + 1
        for item in index.get("pages", []):
            if not isinstance(item, dict):
                continue
            page_number = int(item.get("page_number", 0))
            item["financial_table_count"] = table_counts.get(page_number, 0)
            item["validation_issue_count"] = issue_counts.get(page_number, 0)
            if issue_counts.get(page_number, 0):
                item["review_required"] = True
        await self.storage.write_json(document_id, PAGES_INDEX_PATH, index)
        return result

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

    async def _resolve_batch_translation(
        self,
        document_id: str,
        artifact: str,
        input_hash: str,
        request: TranslationBatchRequest,
        inputs: list[TranslationInput],
    ) -> tuple[TranslationBatchResponse, dict[str, str]]:
        cached_response: TranslationBatchResponse | None = None
        if self.storage.exists(document_id, artifact):
            cached = await self.storage.read_json(document_id, artifact)
            if cached.get("input_hash") == input_hash:
                cached_response = TranslationBatchResponse.model_validate(cached["response"])

        if cached_response is not None:
            invalid = self.validator.validate(inputs, cached_response)
            if not invalid:
                return cached_response, invalid
            # Some cached items still fail validation (e.g. a mangled protected
            # token). Re-request only those specific blocks live - not the whole
            # batch, which would risk drifting the wording of blocks that already
            # translated correctly and cost extra API calls for no reason - and not
            # just re-serving the same cached bad result forever either.
            retry_inputs = [item for item in inputs if item.block_id in invalid]
            retry_block_ids = {item.block_id for item in retry_inputs}
            retry_request = TranslationBatchRequest(
                target_language=request.target_language, blocks=retry_inputs
            )
            fresh_response = await self.translator.translate(retry_request)
            merged_by_id = {item.block_id: item for item in cached_response.translations}
            for item in fresh_response.translations:
                # Only accept results for the block(s) we actually re-requested - a
                # malformed response that echoes back extra/wrong block_ids must not
                # overwrite a different, never-retried block's already-valid cached
                # translation.
                if item.block_id in retry_block_ids:
                    merged_by_id[item.block_id] = item
            response = TranslationBatchResponse(
                translations=[merged_by_id[item.block_id] for item in inputs]
            )
        else:
            response = await self.translator.translate(request)

        invalid = self.validator.validate(inputs, response)
        await self.storage.write_json(
            document_id,
            artifact,
            {
                "input_hash": input_hash,
                "prompt_version": TRANSLATION_PROMPT_VERSION,
                "response": response.model_dump(mode="json"),
            },
        )
        return response, invalid

    async def _translate(
        self,
        document: CanonicalDocument,
        *,
        profile: ProcessingProfile,
        on_batch_progress: ProgressCallback | None = None,
        on_batch_complete: BatchCompleteCallback | None = None,
    ) -> bool:
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
                    review_required=cell.review_required,
                    warnings=list(cell.warnings),
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
            if len(block.source_text) > self.max_batch_chars:
                block.translation_status = TranslationStatus.NEEDS_REVIEW
                block.review_required = True
                block.warnings.append(
                    f"Block exceeds the {self.max_batch_chars}-character translation limit."
                )
                review_required = True
                continue
            if self.language_service.should_translate(block.source_language):
                block.translation_status = TranslationStatus.PENDING
                translatable.append(block)
            elif block.source_language == "en" or not self.language_service.has_letters(
                block.source_text
            ):
                block.translated_text = block.source_text
                block.translation_status = TranslationStatus.NOT_REQUIRED
            else:
                # Defense in depth: should_translate() now only returns False for
                # "en" and "zxx" (both handled above), so this branch shouldn't be
                # reachable - kept as a fail-closed fallback in case that contract
                # ever changes.
                block.translation_status = TranslationStatus.NEEDS_REVIEW
                block.review_required = True
                block.warnings.append("Language could not be confidently routed.")
                review_required = True

        # Collapse identical source strings so repeated financial labels translate once.
        followers: dict[str, list[TextBlock]] = {}
        translation_targets = translatable
        if self.translation_dedupe_identical and translatable:
            representatives: list[TextBlock] = []
            seen: dict[tuple[str, str], TextBlock] = {}
            for block in translatable:
                key = (block.source_language, block.source_text)
                existing = seen.get(key)
                if existing is None:
                    seen[key] = block
                    representatives.append(block)
                else:
                    followers.setdefault(existing.block_id, []).append(block)
            translation_targets = representatives

        batches = self._batches(translation_targets)
        total_batches = len(batches)
        if profile == ProcessingProfile.MANAGED_NO_LLM and translatable:
            for block in translatable:
                block.translation_status = TranslationStatus.NEEDS_REVIEW
                block.review_required = True
                block.warnings.append(
                    "Translation was not sent to a generative model under MANAGED_NO_LLM."
                )
            if on_batch_progress is not None:
                await on_batch_progress(0, 0)
            for cell_id, cell in cell_targets.items():
                target = next(target for target in targets if target.block_id == cell_id)
                cell.source_language = target.source_language
                cell.translated_content = target.translated_text
                cell.translation_status = target.translation_status
                cell.review_required = target.review_required
                cell.warnings = list(target.warnings)
            return True
        if on_batch_progress is not None:
            await on_batch_progress(0, total_batches)

        # Parallelize Azure OpenAI round-trips within one document. Progress/page
        # writes stay serialized so SQLite + pages/index.json stay consistent.
        semaphore = asyncio.Semaphore(self.translation_concurrency)
        io_lock = asyncio.Lock()
        completed = 0
        pending_flush_blocks: list[TextBlock] = []
        batches_since_flush = 0

        async def flush_progress_pages(*, force: bool = False) -> None:
            nonlocal pending_flush_blocks, batches_since_flush
            if on_batch_complete is None:
                pending_flush_blocks = []
                batches_since_flush = 0
                return
            if not pending_flush_blocks:
                return
            if not force and batches_since_flush < self.translation_progress_flush_every:
                return
            flush_blocks = pending_flush_blocks
            pending_flush_blocks = []
            batches_since_flush = 0
            await on_batch_complete(flush_blocks)

        async def run_batch(batch_index: int, blocks: list[TextBlock]) -> None:
            nonlocal completed, review_required, batches_since_flush
            raw_inputs = [
                TranslationInput(
                    block_id=block.block_id,
                    source_language=block.source_language,
                    source_text=block.source_text,
                )
                for block in blocks
            ]
            prepared = self.gateway.prepare_translation_inputs(profile, raw_inputs)
            request = TranslationBatchRequest(blocks=prepared.inputs)
            hash_input = (
                f"{TRANSLATION_PROMPT_VERSION}\n{profile.value}\n{request.model_dump_json()}"
            )
            input_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
            artifact = f"translations/batch-{batch_index:04d}.json"
            batch_failed = False
            async with semaphore:
                try:
                    response, invalid_reasons = await self._resolve_batch_translation(
                        document.document_id,
                        artifact,
                        input_hash,
                        request,
                        prepared.inputs,
                    )
                except (AzureServiceError, TranslationValidationError) as exc:
                    failure_status = (
                        TranslationStatus.FILTERED
                        if isinstance(exc, AzureServiceError)
                        and exc.details.get("reason") == "refusal"
                        else TranslationStatus.FAILED
                    )
                    for block in blocks:
                        block.translation_status = failure_status
                        block.review_required = True
                        block.warnings.append(f"Translation failed: {exc.message}")
                    batch_failed = True
                    await logger.awarning(
                        "translation_batch_failed",
                        document_id=document.document_id,
                        batch_index=batch_index,
                        error_code=exc.code,
                        block_status=failure_status.value,
                    )
                else:
                    translated_by_id = {
                        item.block_id: self.gateway.restore_text(
                            item.translated_text, prepared.token_map
                        )
                        for item in response.translations
                        if item.block_id not in invalid_reasons
                    }
                    # The model detects the real language from the text itself, which
                    # is more reliable than the local script/hint heuristic that fed it
                    # (especially for "und" - a script the heuristic doesn't recognize
                    # at all) - prefer it for the language shown to reviewers.
                    detected_language_by_id: dict[str, str] = {}
                    for item in response.translations:
                        if item.block_id in invalid_reasons:
                            continue
                        detected = LanguageService.normalize_detected_language(
                            item.detected_language
                        )
                        if detected is not None:
                            detected_language_by_id[item.block_id] = detected
                    missing_block_ids = [
                        block.block_id for block in blocks if block.block_id not in translated_by_id
                    ]
                    if missing_block_ids:
                        # Blocks land here either because the model's structured-output
                        # response omitted them (a malformed-but-200 response, not caught
                        # by the AzureServiceError/TranslationValidationError path above)
                        # or because the validator rejected their specific translation
                        # (empty output, or a changed protected number/code/identifier -
                        # see invalid_reasons). Either way, flag only the affected
                        # block(s) for review rather than failing every block in the
                        # batch - the rest translated successfully.
                        await logger.awarning(
                            "translation_batch_missing_block_ids",
                            document_id=document.document_id,
                            batch_index=batch_index,
                            missing_block_ids=missing_block_ids,
                        )
                        batch_failed = True
                    for block in blocks:
                        if block.block_id in translated_by_id:
                            block.translated_text = translated_by_id[block.block_id]
                            block.translation_status = TranslationStatus.TRANSLATED
                            if block.block_id in detected_language_by_id:
                                block.source_language = detected_language_by_id[block.block_id]
                                if not LanguageService.is_benchmarked(block.source_language):
                                    block.review_required = True
                                    block.warnings.append(
                                        "Language outside the currently benchmarked set "
                                        "(Arabic, Chinese, English); verify translation quality."
                                    )
                                    review_required = True
                            else:
                                # The model couldn't identify the language either - this
                                # block looks "done" but nobody, human or model, has
                                # confirmed what was actually translated. Worth a look.
                                block.review_required = True
                                block.warnings.append(
                                    "Translated, but the source language could not be "
                                    "confirmed - please verify."
                                )
                                review_required = True
                        else:
                            block.translation_status = TranslationStatus.FAILED
                            block.review_required = True
                            block.warnings.append(
                                invalid_reasons.get(block.block_id)
                                or "Translation response did not include this block; "
                                "needs manual review."
                            )
                        for follower in followers.get(block.block_id, []):
                            follower.translated_text = block.translated_text
                            follower.translation_status = block.translation_status
                            follower.source_language = block.source_language
                            follower.review_required = block.review_required
                            follower.warnings = list(block.warnings)

            async with io_lock:
                if batch_failed:
                    review_required = True
                    for block in blocks:
                        for follower in followers.get(block.block_id, []):
                            follower.translation_status = block.translation_status
                            follower.review_required = block.review_required
                            follower.warnings = list(block.warnings)
                completed += 1
                if on_batch_progress is not None:
                    await on_batch_progress(completed, total_batches)
                flushed: list[TextBlock] = list(blocks)
                for block in blocks:
                    flushed.extend(followers.get(block.block_id, []))
                pending_flush_blocks.extend(flushed)
                batches_since_flush += 1
                await flush_progress_pages(force=False)

        if total_batches:
            tasks = [
                asyncio.create_task(run_batch(batch_index, blocks))
                for batch_index, blocks in enumerate(batches, start=1)
            ]
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            async with io_lock:
                await flush_progress_pages(force=True)

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

    async def _estimate_pdf_pages(self, source_path: Path) -> int | None:
        if source_path.suffix.lower() != ".pdf":
            return None
        try:
            # See document.py's create_upload for why this must not run inline: it
            # would block the shared event loop that also runs every other worker.
            return await asyncio.to_thread(
                assert_pdf_safe, source_path, max_pages=self.max_document_pages
            )
        except Exception:
            # Upload already validated the PDF; a later estimate miss falls back to
            # single-shot DI rather than failing the whole job.
            return None

    async def _extract_canonical(
        self,
        document_id: str,
        document_record: Any,
        job_id: str,
        *,
        selected_pages: list[int] | None = None,
    ) -> tuple[CanonicalDocument, list[int]]:
        """Extract + normalize, using page-range DI for large PDFs."""
        normalized_path = "normalized/extracted.json"
        if self.storage.exists(document_id, normalized_path):
            canonical = CanonicalDocument.model_validate(
                await self.storage.read_json(document_id, normalized_path)
            )
            source_page_count = int(
                getattr(document_record, "page_count", 0) or len(canonical.pages) or 1
            )
            for page in canonical.pages:
                page.page_count = source_page_count
            page_numbers = await self._write_pages(
                document_id,
                canonical,
                DocumentStatus.NORMALIZING.value,
                only_pages=set(selected_pages) if selected_pages is not None else None,
            )
            await self.repository.update_active_document(
                document_id,
                job_id=job_id,
                page_count=source_page_count,
                pages_ready=len(page_numbers),
                source_languages=canonical.source_languages,
            )
            return canonical, page_numbers

        source_path = self.storage.source_path(document_id, document_record.stored_extension)
        raw_path = "raw/document_intelligence.json"
        extension = str(document_record.stored_extension).lower().lstrip(".")
        estimated_pages = await self._estimate_pdf_pages(source_path)
        trusted_estimate = estimated_pages is not None and estimated_pages > 0
        if not trusted_estimate:
            # Prefer upload/DB page_count when re-parse misses (pages_ready may be None
            # on first run, or lower than the stored target mid-extract).
            stored = getattr(document_record, "page_count", None)
            ready = getattr(document_record, "pages_ready", None)
            if stored and (ready is None or int(stored) > int(ready)):
                estimated_pages = int(stored)
                trusted_estimate = True
        force_range_resume = False

        # Legacy/single-shot resume: full raw artifact already present.
        if self.storage.exists(document_id, raw_path):
            raw = await self.storage.read_json(document_id, raw_path)
            if raw.get("merged_from_ranges"):
                estimated_pages = int(raw.get("page_count") or 0) or estimated_pages
                force_range_resume = True
                trusted_estimate = bool(estimated_pages)
            else:
                await self._stage(document_id, job_id, DocumentStatus.NORMALIZING, 35)
                canonical = self.mapper.map(
                    raw,
                    document_id=document_id,
                    filename=document_record.original_filename,
                )
                return await self._finalize_normalized(
                    document_id,
                    canonical,
                    job_id=job_id,
                    source_page_count=estimated_pages,
                )

        # Unknown page estimate must use ranges — never single-shot a potentially huge PDF.
        use_ranges = selected_pages is not None or force_range_resume or (
            extension == "pdf"
            and (estimated_pages is None or estimated_pages > self.di_page_range_size)
        )

        if not use_ranges:
            await self._stage(document_id, job_id, DocumentStatus.EXTRACTING, 15)
            await self._assert_job_alive(document_id, job_id)
            raw = await self.analyzer.analyze(source_path)
            await self._assert_job_alive(document_id, job_id)
            await self.storage.write_json(document_id, raw_path, raw)
            await self._stage(document_id, job_id, DocumentStatus.NORMALIZING, 35)
            canonical = self.mapper.map(
                raw,
                document_id=document_id,
                filename=document_record.original_filename,
            )
            return await self._finalize_normalized(
                document_id,
                canonical,
                job_id=job_id,
                source_page_count=estimated_pages,
            )

        estimate_is_ceiling = not trusted_estimate
        if estimated_pages is None or estimated_pages < 1:
            # Adaptive fallback: discover page count via successive range calls.
            estimated_pages = self.max_document_pages
            estimate_is_ceiling = True

        ranges = (
            selected_page_ranges(selected_pages, self.di_page_range_size)
            if selected_pages is not None
            else list(page_ranges(estimated_pages, self.di_page_range_size))
        )
        if not ranges:
            raise PolicyBlockedError(
                "No pages were approved for detailed financial extraction."
            )

        # Parallel DI is safe only when the page total is trusted or pages are
        # explicitly selected. Ceiling discovery still needs sequential early-stop.
        parallel_ok = (trusted_estimate or selected_pages is not None) and not estimate_is_ceiling
        range_concurrency = self.di_range_concurrency if parallel_ok else 1

        await self._stage(document_id, job_id, DocumentStatus.EXTRACTING, 15)
        parts_by_start: dict[int, CanonicalDocument] = {}
        ready_pages = 0
        actual_last_page = 0
        completed_ranges = 0
        io_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(range_concurrency)
        stop_remaining = asyncio.Event()

        async def analyze_one_range(
            index: int, start: int, end: int
        ) -> CanonicalDocument | None:
            nonlocal ready_pages, actual_last_page, completed_ranges
            if stop_remaining.is_set():
                return None
            await self._assert_job_alive(document_id, job_id)
            range_artifact = range_artifact_path(start, end)
            pages_param = format_pages_param(start, end)
            if self.storage.exists(document_id, range_artifact):
                raw_part = await self.storage.read_json(document_id, range_artifact)
            else:
                async with semaphore:
                    if stop_remaining.is_set():
                        return None
                    await logger.ainfo(
                        "di_page_range_analyze",
                        document_id=document_id,
                        pages=pages_param,
                        range_index=index,
                        range_total=len(ranges),
                        physical_chunk=self.di_use_physical_chunks
                        and source_path.suffix.lower() == ".pdf",
                    )
                    raw_part = await self._analyze_page_range(
                        document_id,
                        source_path,
                        start=start,
                        end=end,
                    )
                    await self._assert_job_alive(document_id, job_id)
                    await self.storage.write_json(document_id, range_artifact, raw_part)

            pages_in_part = len(raw_part.get("pages") or [])
            expected_in_range = end - start + 1
            is_last_range = index == len(ranges)
            if pages_in_part == 0:
                if estimate_is_ceiling:
                    stop_remaining.set()
                    return None
                if actual_last_page >= estimated_pages:
                    stop_remaining.set()
                    return None
                raise AzureServiceError(
                    f"Document Intelligence returned no pages for range {pages_param}.",
                    retryable=True,
                )

            part = assign_stable_ids(
                self.mapper.map(
                    raw_part,
                    document_id=document_id,
                    filename=document_record.original_filename,
                )
            )
            if trusted_estimate and selected_pages is None:
                if not is_last_range and pages_in_part < expected_in_range:
                    raise AzureServiceError(
                        f"Document Intelligence returned {pages_in_part} pages for "
                        f"range {pages_param}; expected {expected_in_range}.",
                        retryable=True,
                    )

            async with io_lock:
                parts_by_start[start] = part
                if part.pages:
                    actual_last_page = max(
                        actual_last_page, max(p.page_number for p in part.pages)
                    )
                if trusted_estimate and selected_pages is None and is_last_range:
                    if actual_last_page < estimated_pages:
                        raise AzureServiceError(
                            f"Document Intelligence stopped at page {actual_last_page} "
                            f"but this PDF is estimated at {estimated_pages} pages.",
                            retryable=True,
                        )
                page_numbers = await self._write_pages(
                    document_id, part, DocumentStatus.EXTRACTING.value
                )
                ready_pages += len(set(page_numbers))
                completed_ranges += 1
                extract_progress = 15 + int(20 * completed_ranges / max(len(ranges), 1))
                observed_count = max(actual_last_page, ready_pages)
                await self.repository.update_active_document(
                    document_id,
                    job_id=job_id,
                    status=DocumentStatus.EXTRACTING.value,
                    current_stage=DocumentStatus.EXTRACTING.value,
                    progress_percent=extract_progress,
                    page_count=estimated_pages if trusted_estimate else observed_count,
                    pages_ready=ready_pages if selected_pages is not None else observed_count,
                )
                renewed = await self.repository.renew_lease(
                    job_id, self.worker_id, self.job_lease_seconds
                )
                if not renewed:
                    await self._assert_job_alive(document_id, job_id)
                    raise JobLeaseLostError(
                        "This worker's job lease expired and was reclaimed by another worker."
                    )
                if (
                    selected_pages is None
                    and estimate_is_ceiling
                    and pages_in_part < self.di_page_range_size
                ):
                    stop_remaining.set()
            return part

        if range_concurrency == 1:
            for index, (start, end) in enumerate(ranges, start=1):
                if stop_remaining.is_set():
                    break
                await analyze_one_range(index, start, end)
        else:
            tasks = [
                asyncio.create_task(analyze_one_range(index, start, end))
                for index, (start, end) in enumerate(ranges, start=1)
            ]
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                stop_remaining.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        parts = [parts_by_start[start] for start, _end in ranges if start in parts_by_start]
        if not parts:
            raise AzureServiceError(
                "Azure Document Intelligence returned no pages for this document.",
                retryable=False,
            )

        final_page_count = (
            estimated_pages
            if trusted_estimate
            else max(actual_last_page, ready_pages)
        )
        if (
            selected_pages is None
            and trusted_estimate
            and final_page_count < estimated_pages
        ):
            raise AzureServiceError(
                f"Document Intelligence returned {final_page_count} pages "
                f"but this PDF is estimated at {estimated_pages} pages.",
                retryable=True,
            )
        await self.storage.write_json(
            document_id,
            raw_path,
            {
                "merged_from_ranges": True,
                "range_count": len(parts),
                "page_count": final_page_count,
                "range_size": self.di_page_range_size,
                "range_concurrency": range_concurrency,
                "physical_chunks": self.di_use_physical_chunks,
                "selected_pages": selected_pages,
            },
        )
        await self._stage(document_id, job_id, DocumentStatus.NORMALIZING, 38)
        canonical = merge_canonical_parts(
            parts,
            document_id=document_id,
            filename=document_record.original_filename,
        )
        for page in canonical.pages:
            page.page_count = final_page_count
        return await self._finalize_normalized(
            document_id,
            canonical,
            job_id=job_id,
            source_page_count=final_page_count,
        )

    async def _analyze_page_range(
        self,
        document_id: str,
        source_path: Path,
        *,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        """Analyze one page span, preferring a physical PDF chunk to avoid full re-upload."""
        pages_param = format_pages_param(start, end)
        use_chunk = (
            self.di_use_physical_chunks
            and source_path.suffix.lower() == ".pdf"
            and end >= start
        )
        if not use_chunk:
            return await self.analyzer.analyze(source_path, pages=pages_param)

        destination = chunk_pdf_path(self.storage.document_dir(document_id), start, end)
        try:
            await asyncio.to_thread(
                write_pdf_page_chunk, source_path, destination, start, end
            )
            raw_part = await self.analyzer.analyze(destination)
            return remap_di_page_numbers(raw_part, page_offset=start - 1)
        except Exception:
            # Chunking can fail on unusual PDFs; fall back to full-file pages= analysis.
            await logger.awarning(
                "di_physical_chunk_fallback",
                document_id=document_id,
                pages=pages_param,
            )
            return await self.analyzer.analyze(source_path, pages=pages_param)
        finally:
            destination.unlink(missing_ok=True)

    async def _finalize_normalized(
        self,
        document_id: str,
        canonical: CanonicalDocument,
        *,
        job_id: str,
        source_page_count: int | None = None,
    ) -> tuple[CanonicalDocument, list[int]]:
        authoritative_page_count = source_page_count or len(canonical.pages) or 1
        for page in canonical.pages:
            page.page_count = authoritative_page_count
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
        page_numbers = await self._write_pages(
            document_id, canonical, DocumentStatus.NORMALIZING.value
        )
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            page_count=authoritative_page_count,
            pages_ready=len(page_numbers),
            source_languages=canonical.source_languages,
        )
        return canonical, page_numbers

    async def _refresh_source_languages(
        self, document_id: str, job_id: str, canonical: CanonicalDocument
    ) -> None:
        """Recompute the document-level language summary from each block/cell's
        final, post-translation source_language, so it reflects the model's own
        detection (see run_batch's detected_language handling) rather than staying
        stuck on the pre-translation local-heuristic guess _finalize_normalized
        computed before any block had actually been translated."""
        canonical.source_languages = sorted(
            {block.source_language for block in canonical.blocks}
            | {
                cell.source_language
                for table in canonical.tables
                for cell in table.cells
                if cell.content.strip()
            }
        )
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            source_languages=canonical.source_languages,
        )

    async def _finish_safe(
        self,
        document_id: str,
        job_id: str,
        *,
        document_values: dict[str, object],
        job_values: dict[str, object],
    ) -> None:
        await self.repository.finish_processing(
            document_id,
            job_id,
            document_values=document_values,
            job_values=job_values,
            lease_owner=self.worker_id,
        )

    async def process(self, document_id: str) -> None:
        document_record = await self.repository.get(document_id)
        job = await self.repository.latest_job(document_id)
        claimed = await self.repository.claim_job(job.id, self.worker_id, self.job_lease_seconds)
        if not claimed:
            await logger.ainfo(
                "job_claim_skipped",
                document_id=document_id,
                job_id=job.id,
                worker_id=self.worker_id,
            )
            return

        page_numbers: list[int] = []
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.id, stop_heartbeat))
        try:
            try:
                profile = self.gateway.select_profile(
                    data_class=getattr(document_record, "data_class", "synthetic"),
                    requested_profile=getattr(document_record, "processing_profile", None),
                    trusted_stored=True,
                )
            except PolicyBlockedError as exc:
                await self._finish_safe(
                    document_id,
                    job.id,
                    document_values={
                        "status": DocumentStatus.FAILED.value,
                        "current_stage": DocumentStatus.FAILED.value,
                        "error_code": exc.code,
                        "safe_error_message": exc.message,
                    },
                    job_values={
                        "status": JobStatus.FAILED.value,
                        "error_code": exc.code,
                        "safe_error_message": exc.message,
                        "completed_at": datetime.now(UTC),
                        "lease_owner": None,
                        "lease_expires_at": None,
                    },
                )
                return

            classification = await self._classify_financial_pages(
                document_id, document_record, job.id
            )
            selected_pages = classification.selected_pages if classification else None
            extraction_pages = selected_pages
            if (
                selected_pages is not None
                and classification is not None
                and classification.source_page_count > 0
            ):
                density = len(selected_pages) / classification.source_page_count
                if density >= self.di_dense_page_threshold:
                    # Dense financial packet: one full layout pass is cheaper than many
                    # selective ranges that cover almost every page.
                    extraction_pages = None
                    await logger.ainfo(
                        "adaptive_dense_full_extract",
                        document_id=document_id,
                        selected_pages=len(selected_pages),
                        source_pages=classification.source_page_count,
                        density=round(density, 3),
                        threshold=self.di_dense_page_threshold,
                    )
            if selected_pages == []:
                assert classification is not None
                canonical = CanonicalDocument(
                    document_id=document_id,
                    filename=document_record.original_filename,
                    status=DocumentStatus.NORMALIZING.value,
                )
                canonical, page_numbers = await self._finalize_normalized(
                    document_id,
                    canonical,
                    job_id=job.id,
                    source_page_count=classification.source_page_count,
                )
            else:
                canonical, page_numbers = await self._extract_canonical(
                    document_id,
                    document_record,
                    job.id,
                    selected_pages=extraction_pages,
                )
            canonical, reconciliation = self.table_integrity.reconcile(canonical)
            await self.storage.write_json(
                document_id,
                TABLE_RECONCILIATION_PATH,
                reconciliation.model_dump(mode="json"),
            )
            if classification is None:
                classification = await self._classify_from_layout(
                    document_id,
                    canonical,
                    document_record,
                    job.id,
                )
                selected_pages = classification.selected_pages if classification else None

            await self._stage(document_id, job.id, DocumentStatus.TRANSLATING, 45)

            async def on_batch_progress(done: int, total: int) -> None:
                await self._assert_job_alive(document_id, job.id)
                # Translation occupies roughly 45% → 85% of the progress bar.
                translate_progress = 45 if total == 0 else 45 + int(40 * done / total)
                await self.repository.update_active_document(
                    document_id,
                    job_id=job.id,
                    status=DocumentStatus.TRANSLATING.value,
                    current_stage=DocumentStatus.TRANSLATING.value,
                    progress_percent=translate_progress,
                    translation_batches_done=done,
                    translation_batches_total=total,
                )
                renewed = await self.repository.renew_lease(
                    job.id, self.worker_id, self.job_lease_seconds
                )
                if not renewed:
                    await self._assert_job_alive(document_id, job.id)
                    raise JobLeaseLostError(
                        "This worker's job lease expired and was reclaimed by another worker."
                    )

            async def on_batch_complete(batch_blocks: list[TextBlock]) -> None:
                await self._assert_job_alive(document_id, job.id)
                touched = self._pages_touched(batch_blocks)
                if not touched:
                    return
                await self._write_pages(
                    document_id,
                    canonical,
                    DocumentStatus.TRANSLATING.value,
                    only_pages=touched,
                )

            translation_document = self._translation_view(
                canonical,
                set(selected_pages) if selected_pages is not None else None,
            )
            review_required = await self._translate(
                translation_document,
                profile=profile,
                on_batch_progress=on_batch_progress,
                on_batch_complete=on_batch_complete,
            )
            # translation_document is either canonical itself, or a shallow
            # model_copy() over the same block/cell references (see
            # _translation_view) - either way _translate() just mutated the same
            # objects canonical.blocks/tables point to.
            await self._refresh_source_languages(document_id, job.id, canonical)
            financial_result: FinancialResult | None = None
            financial_result_hash: str | None = None
            if classification is not None:
                financial_result = await self._write_financial_result(
                    document_id,
                    canonical,
                    classification,
                    getattr(
                        document_record,
                        "processing_version",
                        CURRENT_PROCESSING_VERSION,
                    ),
                )
                financial_result_hash = financial_result_sha256(financial_result)
                review_required = review_required or financial_result.validation.review_required
                review_required = review_required or any(
                    page.review_required for page in classification.pages if page.selected
                )
            await self._stage(document_id, job.id, DocumentStatus.VALIDATING, 88)
            final_status = (
                DocumentStatus.NEEDS_REVIEW if review_required else DocumentStatus.COMPLETED
            )
            canonical.status = final_status.value

            await self._stage(document_id, job.id, DocumentStatus.EXPORTING, 92)
            stored_financial_mode = str(
                getattr(
                    document_record,
                    "financial_extraction_mode",
                    self.financial_extraction_mode,
                )
            )
            pages_to_write = (
                set(selected_pages)
                if stored_financial_mode == "selective"
                and selected_pages is not None
                else None
            )
            page_numbers = await self._write_pages(
                document_id,
                canonical,
                final_status.value,
                only_pages=pages_to_write,
            )
            source_page_count = int(
                getattr(document_record, "page_count", 0)
                or self._observed_page_count(page_numbers)
                or 1
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
            from app.services.translation_review import bilingual_result_sha256

            translation_result_hash = bilingual_result_sha256(
                canonical.model_dump(mode="json")
            )
            if financial_result is not None:
                await self.storage.write_json(
                    document_id,
                    "exports/financial-document.json",
                    financial_result.model_dump(mode="json"),
                )
            await self.storage.write_json(
                document_id,
                "manifest.json",
                {
                    "schema_version": "1.1",
                    "document_id": document_id,
                    "processing_profile": profile.value,
                    "data_class": getattr(document_record, "data_class", "synthetic"),
                    "source_sha256": getattr(document_record, "sha256", None),
                    "processing_version": getattr(
                        document_record,
                        "processing_version",
                        CURRENT_PROCESSING_VERSION,
                    ),
                    "financial_extraction_mode": stored_financial_mode,
                    "financial_classifier_id": classification.classifier_id
                    if classification is not None
                    else None,
                    "financial_classifier_version": classification.classifier_version
                    if classification is not None
                    else None,
                    "financial_selection_policy_fingerprint": (
                        classification.selection_policy_fingerprint
                        if classification is not None
                        else None
                    ),
                    "financial_result_sha256": financial_result_hash,
                    "translation_result_sha256": translation_result_hash,
                    "document_review_status": (
                        "needs_review" if review_required else "draft"
                    ),
                    "certified": False,
                    "selected_financial_pages": selected_pages or [],
                    "page_count": source_page_count,
                    "detailed_extraction_skipped": selected_pages == [],
                    "artifacts": [
                        *[
                            artifact
                            for artifact in (
                                "raw/document_intelligence.json",
                                "normalized/extracted.json",
                                "exports/extracted-document.json",
                                "exports/bilingual-document.json",
                            )
                            if self.storage.exists(document_id, artifact)
                        ],
                        *(
                            [
                                FINANCIAL_CLASSIFICATION_PATH,
                                TABLE_RECONCILIATION_PATH,
                                FINANCIAL_RESULT_PATH,
                                FINANCIAL_VALIDATION_PATH,
                                "exports/financial-document.json",
                                "exports/financial-document.csv",
                                "exports/financial-document.xlsx",
                            ]
                            if financial_result is not None
                            else []
                        ),
                    ],
                },
            )
            await self._finish_safe(
                document_id,
                job.id,
                document_values={
                    "status": final_status.value,
                    "current_stage": final_status.value,
                    "progress_percent": 100,
                    "page_count": source_page_count,
                    "pages_ready": len(page_numbers),
                    "source_languages": canonical.source_languages,
                    "financial_page_count": len(selected_pages or []),
                    "uncertain_page_count": len(financial_result.uncertain_pages)
                    if financial_result is not None
                    else None,
                    "financial_table_count": len(financial_result.tables)
                    if financial_result is not None
                    else None,
                    "financial_issue_count": financial_result.validation.issue_count
                    if financial_result is not None
                    else None,
                    "financial_result_sha256": financial_result_hash,
                    "translation_result_sha256": translation_result_hash,
                    "document_review_status": (
                        "needs_review" if review_required else "draft"
                    ),
                    "completed_at": datetime.now(UTC),
                },
                job_values={
                    "status": JobStatus.COMPLETED.value,
                    "stage": "completed",
                    "completed_at": datetime.now(UTC),
                    "lease_owner": None,
                    "lease_expires_at": None,
                },
            )
        except JobCancelledError:
            await logger.ainfo(
                "job_cancelled_stop",
                document_id=document_id,
                job_id=job.id,
                worker_id=self.worker_id,
            )
        except JobSupersededError:
            await logger.ainfo(
                "job_superseded_stop",
                document_id=document_id,
                job_id=job.id,
                worker_id=self.worker_id,
            )
        except JobLeaseLostError:
            try:
                await self._assert_job_alive(document_id, job.id)
            except JobCancelledError:
                await logger.ainfo(
                    "job_cancelled_stop",
                    document_id=document_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                )
            except JobSupersededError:
                await logger.ainfo(
                    "job_superseded_stop",
                    document_id=document_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                )
            else:
                await logger.awarning(
                    "job_lease_lost_abandoning_run",
                    document_id=document_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                )
        except AppError as exc:
            try:
                await self._finish_safe(
                    document_id,
                    job.id,
                    document_values={
                        "status": DocumentStatus.FAILED.value,
                        "current_stage": DocumentStatus.FAILED.value,
                        "error_code": exc.code,
                        "safe_error_message": exc.message,
                    },
                    job_values={
                        "status": JobStatus.FAILED.value,
                        "error_code": exc.code,
                        "safe_error_message": exc.message,
                        "completed_at": datetime.now(UTC),
                        "lease_owner": None,
                        "lease_expires_at": None,
                    },
                )
            except JobCancelledError:
                await logger.ainfo(
                    "job_cancelled_stop",
                    document_id=document_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                )
                return
            except JobSupersededError:
                await logger.ainfo(
                    "job_superseded_stop",
                    document_id=document_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                )
                return
            except JobLeaseLostError:
                await logger.awarning(
                    "job_lease_lost_on_failure_write",
                    document_id=document_id,
                    job_id=job.id,
                )
                return
            await self._mark_pages_failed(document_id, page_numbers)
            await logger.awarning(
                "document_processing_failed",
                document_id=document_id,
                error_code=exc.code,
                retryable=getattr(exc, "retryable", False),
            )
        except Exception:
            try:
                await self._finish_safe(
                    document_id,
                    job.id,
                    document_values={
                        "status": DocumentStatus.FAILED.value,
                        "current_stage": DocumentStatus.FAILED.value,
                        "error_code": "processing_failed",
                        "safe_error_message": "Document processing failed unexpectedly.",
                    },
                    job_values={
                        "status": JobStatus.FAILED.value,
                        "error_code": "processing_failed",
                        "safe_error_message": "Document processing failed unexpectedly.",
                        "completed_at": datetime.now(UTC),
                        "lease_owner": None,
                        "lease_expires_at": None,
                    },
                )
            except (JobCancelledError, JobSupersededError, JobLeaseLostError):
                return
            await self._mark_pages_failed(document_id, page_numbers)
            await logger.aexception(
                "document_processing_failed_unexpectedly",
                document_id=document_id,
            )
        finally:
            stop_heartbeat.set()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
