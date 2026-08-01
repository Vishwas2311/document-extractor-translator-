from dataclasses import dataclass

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
    await database.create_schema()
    storage = LocalArtifactStorage(settings.storage_root)
    repository = DocumentRepository(database.session_factory)
    analyzer = DocumentIntelligenceAnalyzer(settings)
    translator = AzureOpenAITranslator(settings)
    processing_service = ProcessingService(
        repository=repository,
        storage=storage,
        analyzer=analyzer,
        mapper=DocumentIntelligenceMapper(),
        translator=translator,
        language_service=LanguageService(),
        validator=TranslationValidator(),
        exporter=ExportService(),
        max_batch_blocks=settings.translation_max_blocks,
        max_batch_chars=settings.translation_max_input_chars,
        ocr_review_threshold=settings.ocr_review_threshold,
    )
    runner = InProcessJobRunner(
        processing_service,
        repository,
        concurrency=settings.processing_concurrency,
    )
    container = ServiceContainer(
        settings=settings,
        database=database,
        storage=storage,
        repository=repository,
        document_service=DocumentService(settings, repository, storage),
        analyzer=analyzer,
        translator=translator,
        processing_service=processing_service,
        runner=runner,
    )
    await runner.start()
    return container
