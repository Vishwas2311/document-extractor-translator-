import asyncio

import structlog

from app.repositories.documents import DocumentRepository
from app.services.processing import ProcessingService

logger = structlog.get_logger(__name__)


class InProcessJobRunner:
    def __init__(
        self,
        processing_service: ProcessingService,
        repository: DocumentRepository,
        concurrency: int = 1,
    ) -> None:
        self.processing_service = processing_service
        self.repository = repository
        self.concurrency = max(1, concurrency)
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.tasks: list[asyncio.Task[None]] = []
        self.enqueued: set[str] = set()

    async def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._worker(index), name=f"document-worker-{index}")
            for index in range(self.concurrency)
        ]
        for document_id in await self.repository.recoverable_document_ids():
            await self.enqueue(document_id)

    async def enqueue(self, document_id: str) -> None:
        if document_id not in self.enqueued:
            self.enqueued.add(document_id)
            await self.queue.put(document_id)

    async def _worker(self, index: int) -> None:
        while True:
            document_id = await self.queue.get()
            if document_id is None:
                self.queue.task_done()
                return
            try:
                await self.processing_service.process(document_id)
            except Exception:
                await logger.aexception(
                    "worker_job_failed",
                    worker_index=index,
                    document_id=document_id,
                )
            finally:
                self.enqueued.discard(document_id)
                self.queue.task_done()

    async def stop(self) -> None:
        for _ in self.tasks:
            await self.queue.put(None)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
