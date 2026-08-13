from dataclasses import dataclass
from uuid import uuid4

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.database.session import Database
from app.integrations.azure_openai.translator import AzureOpenAITranslator
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer
from app.integrations.document_intelligence.mapper import DocumentIntelligenceMapper
from app.repositories.documents import DocumentRepository
from app.services.cost_governor import CostGovernor
from app.services.document import DocumentService
from app.services.export import ExportService
from app.services.financial import FinancialCandidateSelector, FinancialExtractionService
from app.services.language import LanguageService
from app.services.processing import ProcessingService
from app.services.security_gateway import SecurityGateway
from app.services.table_integrity import TableIntegrityService
from app.services.validation import TranslationValidator
from app.storage.local import LocalArtifactStorage
from app.workers.base import JobRunner
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
    runner: JobRunner
    gateway: SecurityGateway
    cost_governor: CostGovernor

    async def close(self) -> None:
        await self.runner.stop()
        await self.analyzer.close()
        await self.translator.close()
        await self.database.dispose()


async def create_container(settings: Settings) -> ServiceContainer:
    # Do not accept a production-looking setting and then silently construct the
    # local adapter. Unsupported adapters fail explicitly until their concrete
    # implementations and integration evidence are present.
    if settings.storage_backend != "local":
        raise ConfigurationError(
            f"Storage backend '{settings.storage_backend}' is not implemented in this build."
        )
    if settings.queue_backend != "in_process":
        raise ConfigurationError(
            f"Queue backend '{settings.queue_backend}' is not implemented in this build."
        )
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
    cost_governor = CostGovernor.from_settings(settings)
    translator = AzureOpenAITranslator(settings, cost_governor)
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
        translation_concurrency=settings.translation_concurrency,
        ocr_review_threshold=settings.ocr_review_threshold,
        worker_id=f"worker-{uuid4().hex[:12]}",
        job_lease_seconds=settings.job_lease_seconds,
        job_heartbeat_seconds=settings.job_heartbeat_seconds,
        di_page_range_size=settings.di_page_range_size,
        max_document_pages=settings.max_document_pages,
        di_range_concurrency=settings.di_range_concurrency,
        di_use_physical_chunks=settings.di_use_physical_chunks,
        di_dense_page_threshold=settings.di_dense_page_threshold,
        translation_dedupe_identical=settings.translation_dedupe_identical,
        translation_progress_flush_every=settings.translation_progress_flush_every,
        financial_selector=FinancialCandidateSelector(
            financial_labels=settings.financial_label_set,
            include_confidence=settings.financial_include_confidence,
            exclude_confidence=settings.financial_exclude_confidence,
            adjacent_pages=settings.financial_adjacent_pages,
        ),
        financial_extractor=FinancialExtractionService(),
        table_integrity=TableIntegrityService(),
        financial_extraction_mode=settings.financial_extraction_mode,
        financial_classifier_model_id=settings.financial_classifier_model_id,
        financial_classifier_version=settings.financial_classifier_version,
        financial_classifier_split_mode=settings.financial_classifier_split_mode,
    )
    runner = InProcessJobRunner(
        processing_service,
        repository,
        concurrency=settings.processing_concurrency,
        recovery_sweep_seconds=settings.recovery_sweep_seconds,
        idempotency_reservation_max_age_seconds=settings.idempotency_reservation_max_age_seconds,
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
        cost_governor=cost_governor,
    )
    await runner.start()
    return container
