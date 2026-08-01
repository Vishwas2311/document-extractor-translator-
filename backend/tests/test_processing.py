from pathlib import Path
from types import SimpleNamespace

from app.core.enums import TranslationStatus
from app.schemas.page import CanonicalDocument, PageMetadata, TableCell, TableResult
from app.schemas.translation import TranslationBatchResponse, TranslationItem
from app.services.language import LanguageService
from app.services.processing import ProcessingService
from app.services.validation import TranslationValidator


class MemoryStorage:
    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}

    def source_path(self, document_id: str, stored_extension: str) -> Path:
        return Path(f"source{stored_extension}")

    def exists(self, document_id: str, relative_path: str) -> bool:
        return False

    async def read_json(self, document_id: str, relative_path: str) -> dict:
        return self.payloads[relative_path]

    async def write_json(self, document_id: str, relative_path: str, payload: dict) -> None:
        self.payloads[relative_path] = payload


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
    service = ProcessingService(
        repository=None,
        storage=storage,
        analyzer=None,
        mapper=None,
        translator=FakeTranslator(),
        language_service=LanguageService(),
        validator=TranslationValidator(),
        exporter=None,
        max_batch_blocks=25,
        max_batch_chars=12000,
        ocr_review_threshold=0.85,
    )
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

    review_required = await service._translate(document)
    cell = document.tables[0].cells[0]

    assert not review_required
    assert cell.cell_id == "t0001-c0001"
    assert cell.source_language == "ar"
    assert cell.translated_content == "English: اسم الشاب"
    assert cell.translation_status == TranslationStatus.TRANSLATED
    assert "translations/batch-0001.json" in storage.payloads


class MemoryRepository:
    def __init__(self) -> None:
        self.document_updates: list[dict[str, object]] = []
        self.job_updates: list[dict[str, object]] = []

    async def get(self, document_id: str):
        return SimpleNamespace(
            id=document_id,
            original_filename="intake.pdf",
            stored_extension=".pdf",
        )

    async def latest_job(self, document_id: str):
        return SimpleNamespace(id="job-1")

    async def update_document(self, document_id: str, **values: object) -> None:
        self.document_updates.append(values)

    async def update_job(self, job_id: str, **values: object) -> None:
        self.job_updates.append(values)


class FakeAnalyzer:
    async def analyze(self, source_path: Path) -> dict:
        return {"status": "succeeded"}


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
    service = ProcessingService(
        repository=repository,
        storage=storage,
        analyzer=FakeAnalyzer(),
        mapper=FakeMapper(),
        translator=MissingOpenAITranslator(),
        language_service=LanguageService(),
        validator=TranslationValidator(),
        exporter=ExportService(),
        max_batch_blocks=25,
        max_batch_chars=12000,
        ocr_review_threshold=0.85,
    )

    await service.process("doc-1")

    page = storage.payloads["pages/page-0001.json"]
    assert page["blocks"][0]["source_text"] == "استمارة دعم الشباب"
    assert page["blocks"][0]["translated_text"] is None
    assert any(update.get("page_count") == 1 for update in repository.document_updates)
    assert repository.document_updates[-1]["status"] == "failed"
    assert repository.document_updates[-1]["error_code"] == "configuration_missing"
