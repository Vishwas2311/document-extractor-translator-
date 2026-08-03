import asyncio
import hashlib
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

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
from app.services.di_ranges import (
    assign_stable_ids,
    format_pages_param,
    merge_canonical_parts,
    page_ranges,
    range_artifact_path,
)
from app.services.export import ExportService
from app.services.language import LanguageService
from app.services.security_gateway import SecurityGateway
from app.services.upload_security import assert_pdf_safe
from app.services.validation import TranslationValidator
from app.storage.local import LocalArtifactStorage

logger = structlog.get_logger(__name__)

PAGES_INDEX_PATH = "pages/index.json"
ProgressCallback = Callable[[int, int], Awaitable[None]]
BatchCompleteCallback = Callable[[list[TextBlock]], Awaitable[None]]



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
        gateway: SecurityGateway,
        *,
        max_batch_blocks: int,
        max_batch_chars: int,
        ocr_review_threshold: float,
        worker_id: str,
        job_lease_seconds: int,
        job_heartbeat_seconds: int = 30,
        di_page_range_size: int = 25,
        max_document_pages: int = 200,
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
        self.ocr_review_threshold = ocr_review_threshold
        self.worker_id = worker_id
        self.job_lease_seconds = job_lease_seconds
        self.job_heartbeat_seconds = max(5, job_heartbeat_seconds)
        self.di_page_range_size = max(1, di_page_range_size)
        self.max_document_pages = max_document_pages

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
            by_number[page.page.page_number] = {
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
    ) -> TranslationBatchResponse:
        if self.storage.exists(document_id, artifact):
            cached = await self.storage.read_json(document_id, artifact)
            if cached.get("input_hash") == input_hash:
                response = TranslationBatchResponse.model_validate(cached["response"])
                self.validator.validate(inputs, response)
                return response
        response = await self.translator.translate(request)
        self.validator.validate(inputs, response)
        await self.storage.write_json(
            document_id,
            artifact,
            {
                "input_hash": input_hash,
                "prompt_version": TRANSLATION_PROMPT_VERSION,
                "response": response.model_dump(mode="json"),
            },
        )
        return response

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
                block.translation_status = TranslationStatus.NEEDS_REVIEW
                block.review_required = True
                block.warnings.append("Language could not be confidently routed.")
                review_required = True

        batches = self._batches(translatable)
        total_batches = len(batches)
        if on_batch_progress is not None:
            await on_batch_progress(0, total_batches)

        for batch_index, blocks in enumerate(batches, start=1):
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
            try:
                response = await self._resolve_batch_translation(
                    document.document_id, artifact, input_hash, request, prepared.inputs
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
                review_required = True
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
                }
                for block in blocks:
                    block.translated_text = translated_by_id[block.block_id]
                    block.translation_status = TranslationStatus.TRANSLATED

            if on_batch_progress is not None:
                await on_batch_progress(batch_index, total_batches)
            if on_batch_complete is not None:
                await on_batch_complete(blocks)

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

    def _estimate_pdf_pages(self, source_path: Path) -> int | None:
        if source_path.suffix.lower() != ".pdf":
            return None
        try:
            return assert_pdf_safe(source_path, max_pages=self.max_document_pages)
        except Exception:
            # Upload already validated the PDF; a later estimate miss falls back to
            # single-shot DI rather than failing the whole job.
            return None

    async def _extract_canonical(
        self,
        document_id: str,
        document_record: Any,
        job_id: str,
    ) -> tuple[CanonicalDocument, list[int]]:
        """Extract + normalize, using page-range DI for large PDFs."""
        normalized_path = "normalized/extracted.json"
        if self.storage.exists(document_id, normalized_path):
            canonical = CanonicalDocument.model_validate(
                await self.storage.read_json(document_id, normalized_path)
            )
            page_numbers = await self._write_pages(
                document_id, canonical, DocumentStatus.NORMALIZING.value
            )
            observed = self._observed_page_count(page_numbers)
            await self.repository.update_active_document(
                document_id,
                job_id=job_id,
                page_count=observed,
                pages_ready=len(page_numbers),
                source_languages=canonical.source_languages,
            )
            return canonical, page_numbers

        source_path = self.storage.source_path(document_id, document_record.stored_extension)
        raw_path = "raw/document_intelligence.json"
        extension = str(document_record.stored_extension).lower().lstrip(".")
        estimated_pages = self._estimate_pdf_pages(source_path)
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
                return await self._finalize_normalized(document_id, canonical, job_id=job_id)

        # Unknown page estimate must use ranges — never single-shot a potentially huge PDF.
        use_ranges = force_range_resume or (
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
            return await self._finalize_normalized(document_id, canonical, job_id=job_id)

        estimate_is_ceiling = not trusted_estimate
        if estimated_pages is None or estimated_pages < 1:
            # Adaptive fallback: discover page count via successive range calls.
            estimated_pages = self.max_document_pages
            estimate_is_ceiling = True

        ranges = list(page_ranges(estimated_pages, self.di_page_range_size))
        parts: list[CanonicalDocument] = []
        ready_pages = 0
        actual_last_page = 0

        for index, (start, end) in enumerate(ranges, start=1):
            await self._assert_job_alive(document_id, job_id)
            range_artifact = range_artifact_path(start, end)
            pages_param = format_pages_param(start, end)
            # Span-keyed artifacts only — never fall back to index-keyed legacy files
            # (those corrupt resume when DI_PAGE_RANGE_SIZE changes).
            if self.storage.exists(document_id, range_artifact):
                raw_part = await self.storage.read_json(document_id, range_artifact)
            else:
                extract_progress = 15 + int(20 * (index - 1) / max(len(ranges), 1))
                await self._stage(document_id, job_id, DocumentStatus.EXTRACTING, extract_progress)
                await logger.ainfo(
                    "di_page_range_analyze",
                    document_id=document_id,
                    pages=pages_param,
                    range_index=index,
                    range_total=len(ranges),
                )
                raw_part = await self.analyzer.analyze(source_path, pages=pages_param)
                await self._assert_job_alive(document_id, job_id)
                await self.storage.write_json(document_id, range_artifact, raw_part)

            pages_in_part = len(raw_part.get("pages") or [])
            expected_in_range = end - start + 1
            is_last_range = end >= estimated_pages
            if pages_in_part == 0:
                # Adaptive/ceiling discovery: empty range means EOF.
                if estimate_is_ceiling:
                    break
                # Trusted total already fully observed.
                if actual_last_page >= estimated_pages:
                    break
                # Empty mid-range with a trusted estimate must not silently truncate.
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
            parts.append(part)
            if part.pages:
                actual_last_page = max(actual_last_page, max(p.page_number for p in part.pages))

            # Trusted estimate: short non-empty ranges must not silently drop pages.
            if trusted_estimate:
                if not is_last_range and pages_in_part < expected_in_range:
                    raise AzureServiceError(
                        f"Document Intelligence returned {pages_in_part} pages for "
                        f"range {pages_param}; expected {expected_in_range}.",
                        retryable=True,
                    )
                if is_last_range and actual_last_page < estimated_pages:
                    raise AzureServiceError(
                        f"Document Intelligence stopped at page {actual_last_page} "
                        f"but this PDF is estimated at {estimated_pages} pages.",
                        retryable=True,
                    )

            # Progressive pages: write this range's pages with stable IDs.
            page_numbers = await self._write_pages(
                document_id, part, DocumentStatus.EXTRACTING.value
            )
            ready_pages = max(ready_pages, actual_last_page, len(page_numbers))
            extract_progress = 15 + int(20 * index / max(len(ranges), 1))
            observed_count = max(actual_last_page, ready_pages)
            await self.repository.update_active_document(
                document_id,
                job_id=job_id,
                status=DocumentStatus.EXTRACTING.value,
                current_stage=DocumentStatus.EXTRACTING.value,
                progress_percent=extract_progress,
                # Never advertise the adaptive ceiling as truth.
                page_count=estimated_pages if trusted_estimate else observed_count,
                pages_ready=observed_count,
            )
            renewed = await self.repository.renew_lease(
                job_id, self.worker_id, self.job_lease_seconds
            )
            if not renewed:
                await self._assert_job_alive(document_id, job_id)
                raise JobLeaseLostError(
                    "This worker's job lease expired and was reclaimed by another worker."
                )

            # Early-stop only when page count was unknown/ceiling and DI returned a short range.
            if estimate_is_ceiling and pages_in_part < self.di_page_range_size:
                break
            # Trusted estimate: keep iterating planned ranges to avoid silent truncation.

        if not parts:
            raise AzureServiceError(
                "Azure Document Intelligence returned no pages for this document.",
                retryable=False,
            )

        final_page_count = max(actual_last_page, ready_pages)
        if trusted_estimate and final_page_count < estimated_pages:
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
            },
        )
        await self._stage(document_id, job_id, DocumentStatus.NORMALIZING, 38)
        canonical = merge_canonical_parts(
            parts,
            document_id=document_id,
            filename=document_record.original_filename,
        )
        return await self._finalize_normalized(document_id, canonical, job_id=job_id)

    async def _finalize_normalized(
        self,
        document_id: str,
        canonical: CanonicalDocument,
        *,
        job_id: str,
    ) -> tuple[CanonicalDocument, list[int]]:
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
        observed = self._observed_page_count(page_numbers)
        await self.repository.update_active_document(
            document_id,
            job_id=job_id,
            page_count=observed,
            pages_ready=len(page_numbers),
            source_languages=canonical.source_languages,
        )
        return canonical, page_numbers

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

            canonical, page_numbers = await self._extract_canonical(
                document_id, document_record, job.id
            )

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

            review_required = await self._translate(
                canonical,
                profile=profile,
                on_batch_progress=on_batch_progress,
                on_batch_complete=on_batch_complete,
            )
            await self._stage(document_id, job.id, DocumentStatus.VALIDATING, 88)
            final_status = (
                DocumentStatus.NEEDS_REVIEW if review_required else DocumentStatus.COMPLETED
            )
            canonical.status = final_status.value

            await self._stage(document_id, job.id, DocumentStatus.EXPORTING, 92)
            page_numbers = await self._write_pages(document_id, canonical, final_status.value)
            observed = self._observed_page_count(page_numbers)
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
                    "processing_profile": profile.value,
                    "data_class": getattr(document_record, "data_class", "synthetic"),
                    "page_count": observed,
                    "artifacts": [
                        "raw/document_intelligence.json",
                        "normalized/extracted.json",
                        "exports/extracted-document.json",
                        "exports/bilingual-document.json",
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
                    "page_count": observed,
                    "pages_ready": len(page_numbers),
                    "source_languages": canonical.source_languages,
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


def clear_raw_range_artifacts(storage: LocalArtifactStorage, document_id: str) -> None:
    """Remove page-range DI artifacts (used by reprocess)."""
    ranges_dir = storage.document_dir(document_id) / "raw" / "ranges"
    if ranges_dir.exists():
        shutil.rmtree(ranges_dir, ignore_errors=True)
