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
        recovery_sweep_seconds: int = 60,
    ) -> None:
        self.processing_service = processing_service
        self.repository = repository
        self.concurrency = max(1, concurrency)
        self.recovery_sweep_seconds = max(15, recovery_sweep_seconds)
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.tasks: list[asyncio.Task[None]] = []
        self.enqueued: set[str] = set()
        self._sweeper: asyncio.Task[None] | None = None

    async def start(self) -> None:
        cleared = await self.repository.clear_stale_leases()
        if cleared:
            await logger.ainfo("stale_leases_cleared", count=cleared)
        self.tasks = [
            asyncio.create_task(self._worker(index), name=f"document-worker-{index}")
            for index in range(self.concurrency)
        ]
        for document_id in await self.repository.recoverable_document_ids():
            await self.enqueue(document_id)
        self._sweeper = asyncio.create_task(self._recovery_loop(), name="job-recovery-sweeper")

    async def enqueue(self, document_id: str) -> None:
        if document_id not in self.enqueued:
            self.enqueued.add(document_id)
            await self.queue.put(document_id)

    async def _recovery_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.recovery_sweep_seconds)
                await self.repository.clear_stale_leases()
                for document_id in await self.repository.recoverable_document_ids():
                    await self.enqueue(document_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await logger.aexception("recovery_sweep_failed")

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
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None
        for _ in self.tasks:
            await self.queue.put(None)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
