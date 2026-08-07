import asyncio
from collections.abc import Sequence
from typing import Protocol

import structlog

from app.core.enums import TERMINAL_DOCUMENT_STATUSES, DocumentStatus
from app.core.exceptions import DocumentNotFoundError

logger = structlog.get_logger(__name__)


class ProcessingWorker(Protocol):
    async def process(self, document_id: str) -> None: ...


class DocumentState(Protocol):
    status: str


class RunnerRepository(Protocol):
    async def clear_stale_leases(self) -> int: ...

    async def recoverable_document_ids(self) -> Sequence[str]: ...

    async def get(self, document_id: str) -> DocumentState: ...


class InProcessJobRunner:
    def __init__(
        self,
        processing_service: ProcessingWorker,
        repository: RunnerRepository,
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
        self.active: set[str] = set()
        # Retries requested while a worker still holds the document.
        self.pending_requeue: set[str] = set()
        self._sweeper: asyncio.Task[None] | None = None

    @property
    def active_count(self) -> int:
        return len(self.active)

    @property
    def pending_count(self) -> int:
        return max(0, self.queue.qsize()) + len(self.pending_requeue)

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
        if document_id in self.enqueued:
            return
        if document_id in self.active:
            # Old worker still finishing (cancel/retry race). Re-enqueue when it exits.
            self.pending_requeue.add(document_id)
            await logger.ainfo("enqueue_deferred_active", document_id=document_id)
            return
        try:
            document = await self.repository.get(document_id)
        except DocumentNotFoundError:
            return
        except Exception:
            await logger.aexception("enqueue_get_failed", document_id=document_id)
            return
        if document.status in {status.value for status in TERMINAL_DOCUMENT_STATUSES}:
            await logger.ainfo(
                "enqueue_skipped_terminal",
                document_id=document_id,
                status=document.status,
            )
            return
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
                document = await self.repository.get(document_id)
                if document.status == DocumentStatus.CANCELLED.value:
                    await logger.ainfo(
                        "worker_skip_cancelled",
                        worker_index=index,
                        document_id=document_id,
                    )
                    continue
                if document.status in {status.value for status in TERMINAL_DOCUMENT_STATUSES}:
                    await logger.ainfo(
                        "worker_skip_terminal",
                        worker_index=index,
                        document_id=document_id,
                        status=document.status,
                    )
                    continue
                # Claim active before releasing enqueued so recovery cannot
                # insert a duplicate queue item in the gap.
                if document_id in self.active:
                    self.pending_requeue.add(document_id)
                    await logger.ainfo(
                        "worker_defer_duplicate_active",
                        worker_index=index,
                        document_id=document_id,
                    )
                    continue
                self.active.add(document_id)
                self.enqueued.discard(document_id)
                try:
                    await self.processing_service.process(document_id)
                finally:
                    self.active.discard(document_id)
                    await self._flush_pending_requeue(document_id)
            except Exception:
                await logger.aexception(
                    "worker_job_failed",
                    worker_index=index,
                    document_id=document_id,
                )
                self.active.discard(document_id)
                await self._flush_pending_requeue(document_id)
            finally:
                self.enqueued.discard(document_id)
                self.queue.task_done()

    async def _flush_pending_requeue(self, document_id: str) -> None:
        if document_id not in self.pending_requeue:
            return
        self.pending_requeue.discard(document_id)
        await self.enqueue(document_id)

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
