from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.core.enums import ProcessingProfile, TranslationStatus
from app.schemas.page import CanonicalDocument, PageMetadata, TableCell, TableResult
from app.schemas.translation import TranslationBatchResponse, TranslationItem
from app.services.language import LanguageService
from app.services.processing import ProcessingService
from app.services.security_gateway import SecurityGateway
from app.services.validation import TranslationValidator


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
        "ocr_review_threshold": 0.85,
        "worker_id": "test-worker",
        "job_lease_seconds": 300,
    }
    defaults.update(kwargs)
    return ProcessingService(**defaults)  # type: ignore[arg-type]


class MemoryStorage:
    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}

    def source_path(self, document_id: str, stored_extension: str) -> Path:
        return Path(f"source{stored_extension}")

    def exists(self, document_id: str, relative_path: str) -> bool:
        return relative_path in self.payloads

    async def read_json(self, document_id: str, relative_path: str) -> dict:
        return self.payloads[relative_path]

    async def write_json(self, document_id: str, relative_path: str, payload: dict) -> None:
        self.payloads[relative_path] = payload

    def document_dir(self, document_id: str) -> Path:
        return Path("storage") / document_id


class FakeTranslator:
    async def translate(self, request) -> TranslationBatchResponse:
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


async def test_numeric_only_blocks_do_not_force_review() -> None:
    storage = MemoryStorage()
    service = _service(storage=storage, translator=FakeTranslator())
    from app.schemas.page import TextBlock

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


class PartiallyFailingTranslator:
    """Fails one batch's worth of blocks; the rest translate normally."""

    async def translate(self, request) -> TranslationBatchResponse:
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
    from app.schemas.page import TextBlock

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


class MemoryRepository:
    def __init__(self) -> None:
        self.document_updates: list[dict[str, object]] = []
        self.job_updates: list[dict[str, object]] = []
        self.status = "queued"
        self.latest_job_id = "job-1"

    async def get(self, document_id: str):
        return SimpleNamespace(
            id=document_id,
            original_filename="intake.pdf",
            stored_extension="pdf",
            data_class="synthetic",
            processing_profile="GENAI_SYNTHETIC_POC",
            status=self.status,
        )

    async def latest_job(self, document_id: str):
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
    async def analyze(self, source_path: Path, *, pages: str | None = None) -> dict:
        return {"status": "succeeded", "pages": pages}


class FakeMapper:
    def map(self, raw: dict, *, document_id: str, filename: str) -> CanonicalDocument:
        from app.schemas.page import BoundingRegion, Point, TextBlock

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
    async def translate(self, request):
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


async def test_batch_complete_rewrites_only_touched_pages() -> None:
    from app.schemas.page import BoundingRegion, Point, TextBlock
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

    async def on_batch_complete(blocks: list) -> None:
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


def _raw_pages(page_numbers: list[int], text: str = "نص") -> dict:
    pages = []
    paragraphs = []
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
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[str | None] = []

    async def analyze(self, source_path: Path, *, pages: str | None = None) -> dict:
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
    service._estimate_pdf_pages = lambda path: 50  # type: ignore[method-assign]

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
    service._estimate_pdf_pages = lambda path: 100  # type: ignore[method-assign]

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
    service._estimate_pdf_pages = lambda path: None  # type: ignore[method-assign]

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
    service._estimate_pdf_pages = lambda path: None  # type: ignore[method-assign]

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


async def test_range_artifacts_are_span_keyed() -> None:
    from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
    from app.services.export import ExportService
    from app.services.di_ranges import range_artifact_path

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
    service._estimate_pdf_pages = lambda path: 50  # type: ignore[method-assign]

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
