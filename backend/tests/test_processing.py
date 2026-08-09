from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.core.enums import ProcessingProfile, TranslationStatus
from app.core.exceptions import PolicyBlockedError
from app.schemas.page import CanonicalDocument, PageMetadata, TableCell, TableResult, TextBlock
from app.schemas.translation import (
    TranslationBatchRequest,
    TranslationBatchResponse,
    TranslationItem,
)
from app.services.language import LanguageService
from app.services.processing import ProcessingService
from app.services.security_gateway import SecurityGateway
from app.services.validation import TranslationValidator


def _async_const(value: int | None) -> Any:
    """Stub for `_estimate_pdf_pages`, which is async (offloaded to a thread)."""

    async def _stub(path: Path) -> int | None:
        return value

    return _stub


def _test_gateway() -> SecurityGateway:
    return SecurityGateway(
        Settings(
            auth_required=False,
            api_auth_tokens="",
            default_processing_profile="GENAI_SYNTHETIC_POC",
            allow_synthetic_raw_llm=True,
            pseudonymization_secret="test",
        )
    )


def _service(**kwargs: object) -> ProcessingService:
    defaults: dict[str, object] = {
        "repository": None,
        "analyzer": None,
        "mapper": None,
        "exporter": None,
        "language_service": LanguageService(),
        "validator": TranslationValidator(),
        "gateway": _test_gateway(),
        "max_batch_blocks": 25,
        "max_batch_chars": 12000,
        "translation_concurrency": 1,
        "di_range_concurrency": 1,
        "di_use_physical_chunks": False,
        "translation_dedupe_identical": False,
        "translation_progress_flush_every": 1,
        "ocr_review_threshold": 0.85,
        "worker_id": "test-worker",
        "job_lease_seconds": 300,
    }
    defaults.update(kwargs)
    return ProcessingService(**defaults)  # type: ignore[arg-type]


class MemoryStorage:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}
        self.text_payloads: dict[str, str] = {}
        self.binary_payloads: dict[str, bytes] = {}

    def source_path(self, document_id: str, stored_extension: str) -> Path:
        return Path(f"source{stored_extension}")

    def exists(self, document_id: str, relative_path: str) -> bool:
        return (
            relative_path in self.payloads
            or relative_path in self.text_payloads
            or relative_path in self.binary_payloads
        )

    async def read_json(
        self, document_id: str, relative_path: str
    ) -> dict[str, Any]:
        return self.payloads[relative_path]

    async def write_json(
        self,
        document_id: str,
        relative_path: str,
        payload: dict[str, Any],
    ) -> None:
        self.payloads[relative_path] = payload

    async def write_text(
        self, document_id: str, relative_path: str, content: str
    ) -> None:
        self.text_payloads[relative_path] = content

    async def write_bytes(
        self, document_id: str, relative_path: str, content: bytes
    ) -> None:
        self.binary_payloads[relative_path] = content

    def document_dir(self, document_id: str) -> Path:
        return Path("storage") / document_id


class FakeTranslator:
    async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
        return TranslationBatchResponse(
            translations=[
                TranslationItem(
                    block_id=item.block_id,
                    translated_text="English: " + item.source_text,
                )
                for item in request.blocks
            ]
        )


async def test_translates_table_cells_with_stable_ids() -> None:
    storage = MemoryStorage()
    service = _service(storage=storage, translator=FakeTranslator())
    document = CanonicalDocument(
        document_id="doc-1",
        filename="table.pdf",
        status="translating",
        pages=[
            PageMetadata(
                page_number=1,
                page_count=1,
                width=8.5,
                height=11,
                unit="inch",
            )
        ],
        tables=[
            TableResult(
                table_id="t0001",
                row_count=1,
                column_count=1,
                cells=[
                    TableCell(
                        cell_id="t0001-c0001",
                        row_index=0,
                        column_index=0,
                        content="اسم الشاب",
                    )
                ],
            )
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )
    cell = document.tables[0].cells[0]

    assert not review_required
    assert cell.cell_id == "t0001-c0001"
    assert cell.source_language == "ar"
    assert cell.translated_content == "English: اسم الشاب"
    assert cell.translation_status == TranslationStatus.TRANSLATED
    assert "translations/batch-0001.json" in storage.payloads



async def test_routes_generic_detected_language_and_reviews_unknown_latin() -> None:
    storage = MemoryStorage()
    service = _service(storage=storage, translator=FakeTranslator())
    document = CanonicalDocument(
        document_id="doc-multilingual",
        filename="languages.pdf",
        status="translating",
        pages=[
            PageMetadata(
                page_number=1,
                page_count=1,
                width=8.5,
                height=11,
                unit="inch",
            )
        ],
        blocks=[
            TextBlock(
                block_id="b-fr",
                reading_order=1,
                source_text="Chiffre d'affaires",
                source_language="fr-FR",
            ),
            TextBlock(
                block_id="b-en",
                reading_order=2,
                source_text="Revenue",
                source_language="en-US",
            ),
            TextBlock(
                block_id="b-und",
                reading_order=3,
                source_text="Texto sin etiqueta",
            ),
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert review_required
    french, english, unknown = document.blocks
    assert french.translation_status == TranslationStatus.TRANSLATED
    assert french.translated_text == "English: Chiffre d'affaires"
    assert english.translation_status == TranslationStatus.NOT_REQUIRED
    assert english.translated_text == "Revenue"
    assert unknown.source_language == "und"
    assert unknown.translation_status == TranslationStatus.NEEDS_REVIEW
    assert unknown.translated_text is None


async def test_numeric_only_blocks_do_not_force_review() -> None:
    storage = MemoryStorage()
    service = _service(storage=storage, translator=FakeTranslator())
    document = CanonicalDocument(
        document_id="doc-2",
        filename="form.pdf",
        status="translating",
        pages=[
            PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")
        ],
        blocks=[
            TextBlock(block_id="b0001", reading_order=1, source_text="2024-01-15"),
            TextBlock(block_id="b0002", reading_order=2, source_text="#42/10"),
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert not review_required
    for block in document.blocks:
        assert block.translation_status == TranslationStatus.NOT_REQUIRED
        assert block.translated_text == block.source_text
        assert not block.review_required


async def test_managed_no_llm_completes_extraction_without_calling_translator() -> None:
    class ForbiddenTranslator:
        async def translate(
            self, request: TranslationBatchRequest
        ) -> TranslationBatchResponse:
            raise AssertionError("MANAGED_NO_LLM must not call a generative translator")

    document = CanonicalDocument(
        document_id="doc-no-llm",
        filename="no-llm.pdf",
        status="translating",
        pages=[
            PageMetadata(
                page_number=1,
                page_count=1,
                width=8.5,
                height=11,
                unit="inch",
            )
        ],
        blocks=[
            TextBlock(
                block_id="b1",
                reading_order=1,
                source_text="مرحبا",
                source_language="ar",
            )
        ],
    )
    service = _service(storage=MemoryStorage(), translator=ForbiddenTranslator())

    review_required = await service._translate(
        document,
        profile=ProcessingProfile.MANAGED_NO_LLM,
    )

    assert review_required
    assert document.blocks[0].translation_status == TranslationStatus.NEEDS_REVIEW
    assert document.blocks[0].review_required


class PartiallyFailingTranslator:
    """Fails one batch's worth of blocks; the rest translate normally."""

    async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
        from app.core.exceptions import AzureServiceError

        if request.blocks[0].block_id == "b0002":
            raise AzureServiceError(
                "Azure OpenAI translation failed after retrying.", retryable=True
            )
        return TranslationBatchResponse(
            translations=[
                TranslationItem(block_id=item.block_id, translated_text="EN: " + item.source_text)
                for item in request.blocks
            ]
        )


async def test_batch_translation_failure_is_isolated_per_block() -> None:
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=PartiallyFailingTranslator(),
        max_batch_blocks=1,
    )
    document = CanonicalDocument(
        document_id="doc-3",
        filename="mixed.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id="b0001", reading_order=1, source_text="مرحبا"),
            TextBlock(block_id="b0002", reading_order=2, source_text="青年支持"),
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert review_required
    first, second = document.blocks
    assert first.translation_status == TranslationStatus.TRANSLATED
    assert first.translated_text == "EN: مرحبا"
    # The failing batch is isolated to its own blocks - it doesn't prevent the rest of
    # the document (first block) from translating successfully.
    assert second.translation_status == TranslationStatus.FAILED
    assert second.review_required
    assert any("Translation failed" in warning for warning in second.warnings)


class MissingBlockIdTranslator:
    """Returns a well-formed (200-status) response that simply omits one requested
    block_id - the malformed-but-successful case, distinct from an API error."""

    async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
        return TranslationBatchResponse(
            translations=[
                TranslationItem(block_id=item.block_id, translated_text="EN: " + item.source_text)
                for item in request.blocks
                if item.block_id != "b0002"
            ]
        )


class NoOpTranslationValidator:
    """A validator that never raises - stands in for `TranslationValidator` to prove
    the block-mapping code itself degrades gracefully on a missing block_id, rather
    than relying solely on `TranslationValidator.validate()` (which already rejects an
    ID-set mismatch before this code runs in the real, default-configured pipeline).
    Defense in depth: if validation is ever relaxed, replaced, or misconfigured, a
    missing block_id must still fail closed *for that block only*, not raise an
    unhandled KeyError that takes down the whole document."""

    def validate(self, inputs: list[object], response: TranslationBatchResponse) -> None:
        return None


async def test_batch_translation_missing_block_id_is_isolated_per_block() -> None:
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=MissingBlockIdTranslator(),
        validator=NoOpTranslationValidator(),
        max_batch_blocks=25,
    )
    document = CanonicalDocument(
        document_id="doc-4",
        filename="mixed.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id="b0001", reading_order=1, source_text="مرحبا"),
            TextBlock(block_id="b0002", reading_order=2, source_text="青年支持"),
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert review_required
    first, second = document.blocks
    # A response missing one block_id doesn't crash or fail the whole batch - the
    # block that *was* present in the response still translates normally.
    assert first.translation_status == TranslationStatus.TRANSLATED
    assert first.translated_text == "EN: مرحبا"
    assert second.translation_status == TranslationStatus.FAILED
    assert second.review_required
    assert any("did not include this block" in warning for warning in second.warnings)


async def test_default_validator_rejects_missing_block_id_at_the_batch_level() -> None:
    """Documents current, real behavior with the actual (non-stubbed)
    `TranslationValidator`: it already rejects an ID-set mismatch before the
    block-mapping code in `run_batch` ever runs, so a missing block_id fails the whole
    *batch* it was requested in (not the whole document - other batches are
    unaffected), via the pre-existing `TranslationValidationError` handling."""
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=MissingBlockIdTranslator(),
        max_batch_blocks=25,
    )
    document = CanonicalDocument(
        document_id="doc-5",
        filename="mixed.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id="b0001", reading_order=1, source_text="مرحبا"),
            TextBlock(block_id="b0002", reading_order=2, source_text="青年支持"),
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert review_required
    first, second = document.blocks
    assert first.translation_status == TranslationStatus.FAILED
    assert second.translation_status == TranslationStatus.FAILED
    assert any("Translation failed" in warning for warning in first.warnings)


class MemoryRepository:
    def __init__(self) -> None:
        self.document_updates: list[dict[str, object]] = []
        self.job_updates: list[dict[str, object]] = []
        self.status = "queued"
        self.latest_job_id = "job-1"

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            original_filename="intake.pdf",
            stored_extension="pdf",
            data_class="synthetic",
            processing_profile="GENAI_SYNTHETIC_POC",
            status=self.status,
        )

    async def latest_job(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=self.latest_job_id, status="running")

    async def assert_job_is_current(self, document_id: str, job_id: str) -> None:
        if self.status == "cancelled":
            from app.core.exceptions import JobCancelledError

            raise JobCancelledError("Processing was cancelled.")
        if job_id != self.latest_job_id:
            from app.core.exceptions import JobSupersededError

            raise JobSupersededError("A newer processing job replaced this worker.")

    async def update_document(self, document_id: str, **values: object) -> None:
        self.document_updates.append(values)
        if "status" in values:
            self.status = str(values["status"])

    async def update_active_document(
        self, document_id: str, *, job_id: str, **values: object
    ) -> None:
        await self.assert_job_is_current(document_id, job_id)
        await self.update_document(document_id, **values)

    async def is_cancelled(self, document_id: str) -> bool:
        return self.status == "cancelled"

    async def update_job(self, job_id: str, **values: object) -> None:
        self.job_updates.append(values)

    async def update_active_job(self, job_id: str, **values: object) -> None:
        await self.assert_job_is_current("doc", job_id)
        self.job_updates.append(values)

    async def claim_job(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        return True

    async def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        return True

    async def finish_processing(
        self,
        document_id: str,
        job_id: str,
        *,
        document_values: dict[str, object],
        job_values: dict[str, object],
        lease_owner: str | None = None,
    ) -> None:
        await self.assert_job_is_current(document_id, job_id)
        self.document_updates.append(document_values)
        self.job_updates.append(job_values)
        if "status" in document_values:
            self.status = str(document_values["status"])


class FakeAnalyzer:
    async def analyze(
        self, source_path: Path, *, pages: str | None = None
    ) -> dict[str, Any]:
        return {"status": "succeeded", "pages": pages}


class NonFinancialAnalyzer(FakeAnalyzer):
    async def classify(
        self,
        source_path: Path,
        *,
        classifier_id: str,
        split_mode: str,
    ) -> dict[str, object]:
        return {
            "documents": [
                {
                    "docType": "non_financial",
                    "confidence": 0.99,
                    "boundingRegions": [{"pageNumber": 1}],
                }
            ]
        }

    async def analyze(
        self, source_path: Path, *, pages: str | None = None
    ) -> dict[str, Any]:
        raise AssertionError("No page should be sent to detailed extraction.")


class FakeMapper:
    def map(
        self, raw: dict[str, Any], *, document_id: str, filename: str
    ) -> CanonicalDocument:
        from app.schemas.page import BoundingRegion, Point

        return CanonicalDocument(
            document_id=document_id,
            filename=filename,
            status="normalizing",
            pages=[
                PageMetadata(
                    page_number=1,
                    page_count=1,
                    width=8.5,
                    height=11,
                    unit="inch",
                    source_text="استمارة دعم الشباب",
                )
            ],
            blocks=[
                TextBlock(
                    block_id="b0001",
                    reading_order=1,
                    source_text="استمارة دعم الشباب",
                    source_language="ar",
                    bounding_regions=[
                        BoundingRegion(
                            page_number=1,
                            polygon=[
                                Point(x=1, y=1),
                                Point(x=7, y=1),
                                Point(x=7, y=2),
                                Point(x=1, y=2),
                            ],
                        )
                    ],
                )
            ],
        )


class MissingOpenAITranslator:
    async def translate(
        self, request: TranslationBatchRequest
    ) -> TranslationBatchResponse:
        from app.core.exceptions import ConfigurationError

        raise ConfigurationError("Azure OpenAI is not configured. Add the endpoint and key.")


async def test_preserves_extraction_when_translation_is_not_configured() -> None:
    from app.services.export import ExportService

    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=FakeAnalyzer(),
        mapper=FakeMapper(),
        translator=MissingOpenAITranslator(),
        exporter=ExportService(),
    )

    await service.process("doc-1")

    page = storage.payloads["pages/page-0001.json"]
    assert page["blocks"][0]["source_text"] == "استمارة دعم الشباب"
    assert page["blocks"][0]["translated_text"] is None
    assert any(update.get("page_count") == 1 for update in repository.document_updates)
    assert repository.document_updates[-1]["status"] == "failed"
    assert repository.document_updates[-1]["error_code"] == "configuration_missing"


async def test_selective_empty_selection_completes_with_consistent_exports() -> None:
    from app.services.export import ExportService
    from app.services.financial import (
        FinancialCandidateSelector,
        FinancialExtractionService,
    )

    repository = MemoryRepository()
    storage = MemoryStorage()
    selector = FinancialCandidateSelector(
        financial_labels={"balance_sheet", "financial_table"},
        include_confidence=0.65,
        exclude_confidence=0.9,
        adjacent_pages=0,
    )
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=NonFinancialAnalyzer(),
        mapper=FakeMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        financial_selector=selector,
        financial_extractor=FinancialExtractionService(),
        financial_extraction_mode="selective",
        financial_classifier_model_id="finance-classifier",
        financial_classifier_version="7",
    )

    await service.process("doc-empty")

    assert repository.document_updates[-1]["status"] == "completed"
    assert storage.payloads["normalized/extracted.json"]["pages"] == []
    assert storage.payloads["normalized/financial.json"]["selected_pages"] == []
    assert storage.payloads["exports/extracted-document.json"]["pages"] == []
    assert storage.payloads["manifest.json"]["detailed_extraction_skipped"] is True
    assert "raw/document_intelligence.json" not in storage.payloads
    assert "exports/financial-document.csv" in storage.text_payloads
    assert "exports/financial-document.xlsx" in storage.binary_payloads


async def test_invalid_cached_financial_classification_fails_closed() -> None:
    from app.services.financial import FinancialCandidateSelector

    storage = MemoryStorage()
    storage.payloads["classification/pages.json"] = {
        "schema_version": "financial-classification-1.1",
        "document_id": "doc-cache",
        "source_page_count": 2,
        "pages": [],
    }
    selector = FinancialCandidateSelector(
        financial_labels={"balance_sheet"},
        include_confidence=0.65,
        exclude_confidence=0.9,
        adjacent_pages=0,
    )
    service = _service(
        storage=storage,
        translator=FakeTranslator(),
        financial_selector=selector,
        financial_extraction_mode="selective",
        financial_classifier_model_id="finance-classifier",
        financial_classifier_version="7",
    )

    with pytest.raises(PolicyBlockedError, match="cached financial classification is invalid"):
        await service._classify_financial_pages(
            "doc-cache",
            SimpleNamespace(
                financial_extraction_mode="selective",
                page_count=2,
                stored_extension="pdf",
            ),
            "job-cache",
        )


async def test_batch_complete_rewrites_only_touched_pages() -> None:
    from app.schemas.page import BoundingRegion, Point
    from app.services.export import ExportService

    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=FakeTranslator(),
        exporter=ExportService(),
        max_batch_blocks=1,
    )
    document = CanonicalDocument(
        document_id="doc-touch",
        filename="two.pdf",
        status="translating",
        pages=[
            PageMetadata(page_number=1, page_count=2, width=8.5, height=11, unit="inch"),
            PageMetadata(page_number=2, page_count=2, width=8.5, height=11, unit="inch"),
        ],
        blocks=[
            TextBlock(
                block_id="p0001-b0001",
                reading_order=1,
                source_text="مرحبا",
                bounding_regions=[
                    BoundingRegion(
                        page_number=1,
                        polygon=[
                            Point(x=1, y=1),
                            Point(x=2, y=1),
                            Point(x=2, y=2),
                            Point(x=1, y=2),
                        ],
                    )
                ],
            ),
            TextBlock(
                block_id="p0002-b0001",
                reading_order=2,
                source_text="青年",
                bounding_regions=[
                    BoundingRegion(
                        page_number=2,
                        polygon=[
                            Point(x=1, y=1),
                            Point(x=2, y=1),
                            Point(x=2, y=2),
                            Point(x=1, y=2),
                        ],
                    )
                ],
            ),
        ],
    )

    written: list[set[int]] = []

    async def on_batch_complete(blocks: list[TextBlock]) -> None:
        touched = service._pages_touched(blocks)
        written.append(set(touched))
        await service._write_pages(
            document.document_id,
            document,
            "translating",
            only_pages=touched,
        )

    await service._translate(
        document,
        profile=ProcessingProfile.GENAI_SYNTHETIC_POC,
        on_batch_complete=on_batch_complete,
    )

    assert written == [{1}, {2}]
    assert "pages/page-0001.json" in storage.payloads
    assert "pages/page-0002.json" in storage.payloads
    assert "pages/index.json" in storage.payloads
    assert [item["page_number"] for item in storage.payloads["pages/index.json"]["pages"]] == [
        1,
        2,
    ]


class ConcurrentFakeTranslator:
    """Tracks overlapping in-flight Azure OpenAI calls."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
        import asyncio

        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.05)
        self.in_flight -= 1
        return TranslationBatchResponse(
            translations=[
                TranslationItem(
                    block_id=item.block_id,
                    translated_text="EN: " + item.source_text,
                )
                for item in request.blocks
            ]
        )


async def test_translation_batches_run_in_parallel() -> None:
    translator = ConcurrentFakeTranslator()
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=translator,
        max_batch_blocks=1,
        translation_concurrency=4,
    )
    document = CanonicalDocument(
        document_id="doc-parallel",
        filename="parallel.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id=f"b{i:04d}", reading_order=i, source_text=f"مرحبا {i}")
            for i in range(1, 9)
        ],
    )

    review_required = await service._translate(
        document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC
    )

    assert not review_required
    assert translator.calls == 8
    assert translator.max_in_flight >= 4
    assert all(
        block.translation_status == TranslationStatus.TRANSLATED
        for block in document.blocks
    )
    assert len([path for path in storage.payloads if path.startswith("translations/")]) == 8


async def test_parallel_batch_progress_is_monotonic() -> None:
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=ConcurrentFakeTranslator(),
        max_batch_blocks=1,
        translation_concurrency=3,
    )
    document = CanonicalDocument(
        document_id="doc-progress",
        filename="progress.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id=f"b{i:04d}", reading_order=i, source_text=f"青年 {i}")
            for i in range(1, 7)
        ],
    )
    progress_events: list[tuple[int, int]] = []

    async def on_batch_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    await service._translate(
        document,
        profile=ProcessingProfile.GENAI_SYNTHETIC_POC,
        on_batch_progress=on_batch_progress,
    )

    assert progress_events[0] == (0, 6)
    done_values = [done for done, _total in progress_events[1:]]
    assert done_values == list(range(1, 7))


def _raw_pages(page_numbers: list[int], text: str = "نص") -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    offset = 0
    content_parts: list[str] = []
    for number in page_numbers:
        piece = f"{text}-{number}"
        content_parts.append(piece)
        length = len(piece)
        pages.append(
            {
                "pageNumber": number,
                "width": 8.5,
                "height": 11,
                "unit": "inch",
                "spans": [{"offset": offset, "length": length}],
            }
        )
        paragraphs.append(
            {
                "content": piece,
                "spans": [{"offset": offset, "length": length}],
                "boundingRegions": [
                    {"pageNumber": number, "polygon": [1, 1, 4, 1, 4, 2, 1, 2]}
                ],
            }
        )
        offset += length + 1
    return {
        "content": "\n".join(content_parts),
        "pages": pages,
        "paragraphs": paragraphs,
    }


class RangeAnalyzer:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str | None] = []

    async def analyze(
        self, source_path: Path, *, pages: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(pages)
        if pages is None:
            return self.responses.get("full", {"pages": []})
        return self.responses.get(pages, {"pages": []})


async def test_trusted_empty_mid_range_raises_instead_of_truncating() -> None:
    from app.core.exceptions import AzureServiceError
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "1-25": _raw_pages(list(range(1, 26))),
            "26-50": {"pages": []},
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
    )
    service._estimate_pdf_pages = _async_const(50)  # type: ignore[method-assign]

    document_record = SimpleNamespace(
        original_filename="large.pdf",
        stored_extension="pdf",
        page_count=None,
        pages_ready=None,
    )

    try:
        await service._extract_canonical("doc-mid", document_record, "job-1")
        raise AssertionError("expected AzureServiceError")
    except AzureServiceError as exc:
        assert "26-50" in exc.message
    assert analyzer.calls == ["1-25", "26-50"]


async def test_trusted_short_mid_range_raises_instead_of_truncating() -> None:
    from app.core.exceptions import AzureServiceError
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "1-25": _raw_pages(list(range(1, 26))),
            # Non-empty but incomplete mid-range — must fail closed.
            "26-50": _raw_pages(list(range(26, 41))),
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
    )
    service._estimate_pdf_pages = _async_const(100)  # type: ignore[method-assign]

    try:
        await service._extract_canonical(
            "doc-short",
            SimpleNamespace(
                original_filename="short.pdf",
                stored_extension="pdf",
                page_count=None,
                pages_ready=None,
            ),
            "job-1",
        )
        raise AssertionError("expected AzureServiceError")
    except AzureServiceError as exc:
        assert "26-50" in exc.message or "expected 25" in exc.message


async def test_stored_page_count_used_when_reparse_misses() -> None:
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "1-25": _raw_pages(list(range(1, 26))),
            "26-30": _raw_pages(list(range(26, 31))),
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
    )
    service._estimate_pdf_pages = _async_const(None)  # type: ignore[method-assign]

    canonical, page_numbers = await service._extract_canonical(
        "doc-stored",
        SimpleNamespace(
            original_filename="stored.pdf",
            stored_extension="pdf",
            page_count=30,
            pages_ready=None,
        ),
        "job-1",
    )

    assert analyzer.calls == ["1-25", "26-30"]
    assert max(page_numbers) == 30
    assert canonical.pages[-1].page_count == 30


async def test_unknown_page_estimate_uses_ranges_not_single_shot() -> None:
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "1-25": _raw_pages(list(range(1, 11))),
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
        max_document_pages=200,
    )
    service._estimate_pdf_pages = _async_const(None)  # type: ignore[method-assign]

    document_record = SimpleNamespace(
        original_filename="unknown.pdf",
        stored_extension="pdf",
        page_count=None,
        pages_ready=None,
    )

    canonical, page_numbers = await service._extract_canonical(
        "doc-unknown", document_record, "job-1"
    )

    assert analyzer.calls == ["1-25"]
    assert "full" not in analyzer.calls
    assert max(page_numbers) == 10
    assert canonical.pages[-1].page_count == 10
    assert "raw/ranges/range-0001-0025.json" in storage.payloads


async def test_selective_extraction_requests_only_candidate_ranges() -> None:
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "2-3": _raw_pages([2, 3]),
            "40": _raw_pages([40]),
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
    )
    service._estimate_pdf_pages = _async_const(50)  # type: ignore[method-assign]

    canonical, page_numbers = await service._extract_canonical(
        "doc-selective",
        SimpleNamespace(
            original_filename="selective.pdf",
            stored_extension="pdf",
            page_count=50,
            pages_ready=None,
        ),
        "job-1",
        selected_pages=[2, 3, 40],
    )

    assert analyzer.calls == ["2-3", "40"]
    assert page_numbers == [2, 3, 40]
    assert {page.page_number for page in canonical.pages} == {2, 3, 40}
    assert all(page.page_count == 50 for page in canonical.pages)
    assert repository.document_updates[-1]["page_count"] == 50
    assert repository.document_updates[-1]["pages_ready"] == 3


async def test_range_artifacts_are_span_keyed() -> None:
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.di_ranges import range_artifact_path
    from app.services.export import ExportService

    analyzer = RangeAnalyzer(
        {
            "1-25": _raw_pages(list(range(1, 26))),
            "26-50": _raw_pages(list(range(26, 51))),
        }
    )
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
    )
    service._estimate_pdf_pages = _async_const(50)  # type: ignore[method-assign]

    await service._extract_canonical(
        "doc-span",
        SimpleNamespace(
            original_filename="span.pdf",
            stored_extension="pdf",
            page_count=None,
            pages_ready=None,
        ),
        "job-1",
    )

    assert range_artifact_path(1, 25) in storage.payloads
    assert range_artifact_path(26, 50) in storage.payloads
    assert "raw/ranges/range-0001.json" not in storage.payloads


async def test_translation_dedupes_identical_source_strings() -> None:
    class CountingTranslator:
        def __init__(self) -> None:
            self.calls = 0

        async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
            self.calls += 1
            return TranslationBatchResponse(
                translations=[
                    TranslationItem(
                        block_id=item.block_id,
                        translated_text="EN:" + item.source_text,
                    )
                    for item in request.blocks
                ]
            )

    translator = CountingTranslator()
    storage = MemoryStorage()
    service = _service(
        storage=storage,
        translator=translator,
        max_batch_blocks=10,
        translation_dedupe_identical=True,
    )
    document = CanonicalDocument(
        document_id="doc-dedupe",
        filename="dedupe.pdf",
        status="translating",
        pages=[PageMetadata(page_number=1, page_count=1, width=8.5, height=11, unit="inch")],
        blocks=[
            TextBlock(block_id="b1", reading_order=1, source_text="الإجمالي"),
            TextBlock(block_id="b2", reading_order=2, source_text="الإجمالي"),
            TextBlock(block_id="b3", reading_order=3, source_text="الإجمالي"),
        ],
    )

    await service._translate(document, profile=ProcessingProfile.GENAI_SYNTHETIC_POC)

    assert translator.calls == 1
    assert [block.translated_text for block in document.blocks] == [
        "EN:الإجمالي",
        "EN:الإجمالي",
        "EN:الإجمالي",
    ]


async def test_parallel_di_ranges_honor_concurrency_cap() -> None:
    import asyncio

    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService

    class ParallelRangeAnalyzer:
        def __init__(self) -> None:
            self.in_flight = 0
            self.max_in_flight = 0
            self.calls: list[str | None] = []
            self._lock = asyncio.Lock()

        async def analyze(
            self, source_path: Path, *, pages: str | None = None
        ) -> dict[str, Any]:
            async with self._lock:
                self.calls.append(pages)
                self.in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.05)
            start, end = (pages or "1-1").split("-")
            start_i = int(start)
            end_i = int(end)
            async with self._lock:
                self.in_flight -= 1
            return _raw_pages(list(range(start_i, end_i + 1)))

    analyzer = ParallelRangeAnalyzer()
    repository = MemoryRepository()
    storage = MemoryStorage()
    service = _service(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=FakeTranslator(),
        exporter=ExportService(),
        di_page_range_size=25,
        di_range_concurrency=2,
        di_use_physical_chunks=False,
    )
    service._estimate_pdf_pages = _async_const(50)  # type: ignore[method-assign]

    await service._extract_canonical(
        "doc-parallel-di",
        SimpleNamespace(
            original_filename="parallel.pdf",
            stored_extension="pdf",
            page_count=50,
            pages_ready=None,
        ),
        "job-1",
    )

    assert analyzer.max_in_flight == 2
    assert sorted(call for call in analyzer.calls if call is not None) == ["1-25", "26-50"]
