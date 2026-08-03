from dataclasses import dataclass
from uuid import uuid4

from app.core.config import Settings
from app.database.session import Database
from app.integrations.azure_openai.translator import AzureOpenAITranslator
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer
from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
from app.repositories.documents import DocumentRepository
from app.services.document import DocumentService
from app.services.export import ExportService
from app.services.language import LanguageService
from app.services.processing import ProcessingService
from app.services.security_gateway import SecurityGateway
from app.services.validation import TranslationValidator
from app.storage.local import LocalArtifactStorage
from app.workers.runner import InProcessJobRunner


@dataclass
class ServiceContainer:
    settings: Settings
    database: Database
    storage: LocalArtifactStorage
    repository: DocumentRepository
    document_service: DocumentService
    analyzer: DocumentIntelligenceAnalyzer
    translator: AzureOpenAITranslator
    processing_service: ProcessingService
    runner: InProcessJobRunner
    gateway: SecurityGateway

    async def close(self) -> None:
        await self.runner.stop()
        await self.analyzer.close()
        await self.translator.close()
        await self.database.dispose()


async def create_container(settings: Settings) -> ServiceContainer:
    database_url = settings.database_url
    if database_url is None:
        raise RuntimeError("Database URL was not resolved.")
    database = Database(database_url)
    if settings.use_create_all:
        await database.create_schema()
        await database.ensure_prd_columns()
    storage = LocalArtifactStorage(settings.storage_root)
    repository = DocumentRepository(database.session_factory)
    analyzer = DocumentIntelligenceAnalyzer(settings)
    translator = AzureOpenAITranslator(settings)
    gateway = SecurityGateway(settings)
    processing_service = ProcessingService(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=translator,
        language_service=LanguageService(),
        validator=TranslationValidator(),
        exporter=ExportService(),
        gateway=gateway,
        max_batch_blocks=settings.translation_max_blocks,
        max_batch_chars=settings.translation_max_input_chars,
        ocr_review_threshold=settings.ocr_review_threshold,
        worker_id=f"worker-{uuid4().hex[:12]}",
        job_lease_seconds=settings.job_lease_seconds,
        job_heartbeat_seconds=settings.job_heartbeat_seconds,
        di_page_range_size=settings.di_page_range_size,
        max_document_pages=settings.max_document_pages,
    )
    runner = InProcessJobRunner(
        processing_service,
        repository,
        concurrency=settings.processing_concurrency,
        recovery_sweep_seconds=settings.recovery_sweep_seconds,
    )
    container = ServiceContainer(
        settings=settings,
        database=database,
        storage=storage,
        repository=repository,
        document_service=DocumentService(settings, repository, storage, gateway),
        analyzer=analyzer,
        translator=translator,
        processing_service=processing_service,
        runner=runner,
        gateway=gateway,
    )
    await runner.start()
    return container
