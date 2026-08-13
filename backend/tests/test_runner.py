"""In-process job runner enqueue / requeue semantics."""

import asyncio
from types import SimpleNamespace

from app.core.enums import DocumentStatus
from app.workers.runner import InProcessJobRunner


class SlowProcessing:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.runs: list[str] = []

    async def process(self, document_id: str) -> None:
        self.runs.append(document_id)
        self.started.set()
        await self.release.wait()


class FakeRepo:
    def __init__(self, status: str = DocumentStatus.QUEUED.value) -> None:
        self.status = status
        self.idempotency_sweep_calls: list[int] = []

    async def clear_stale_leases(self) -> int:
        return 0

    async def clear_stale_idempotency_reservations(self, *, max_age_seconds: int) -> int:
        self.idempotency_sweep_calls.append(max_age_seconds)
        return 0

    async def recoverable_document_ids(self) -> list[str]:
        return []

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=document_id, status=self.status)


async def test_start_sweeps_stale_idempotency_reservations() -> None:
    """Regression: reserve_idempotency's in-flight rows were never reclaimed
    after a crash/restart, permanently 409ing any retry with that key. The
    sweep must run at startup, mirroring the existing stale-lease sweep."""
    processing = SlowProcessing()
    repo = FakeRepo()
    runner = InProcessJobRunner(
        processing,
        repo,
        concurrency=1,
        recovery_sweep_seconds=60,
        idempotency_reservation_max_age_seconds=1800,
    )

    await runner.start()

    assert repo.idempotency_sweep_calls == [1800]
    await runner.stop()


async def test_enqueue_while_active_is_deferred_then_flushed() -> None:
    processing = SlowProcessing()
    repo = FakeRepo()
    runner = InProcessJobRunner(processing, repo, concurrency=1, recovery_sweep_seconds=60)
    runner.tasks = [asyncio.create_task(runner._worker(0))]

    await runner.enqueue("doc-1")
    await asyncio.wait_for(processing.started.wait(), timeout=2)

    # Retry while old worker still active — must not drop.
    repo.status = DocumentStatus.QUEUED.value
    await runner.enqueue("doc-1")
    assert "doc-1" in runner.pending_requeue
    assert runner.queue.qsize() == 0

    processing.release.set()
    # Allow worker to flush pending requeue and run again.
    for _ in range(50):
        if len(processing.runs) >= 2:
            break
        await asyncio.sleep(0.02)

    assert processing.runs == ["doc-1", "doc-1"]
    assert "doc-1" not in runner.pending_requeue

    await runner.stop()


async def test_duplicate_queue_item_defers_while_active() -> None:
    """Recovery must not start a second process while one is already active."""
    processing = SlowProcessing()
    repo = FakeRepo()
    runner = InProcessJobRunner(processing, repo, concurrency=2, recovery_sweep_seconds=60)
    runner.tasks = [
        asyncio.create_task(runner._worker(0)),
        asyncio.create_task(runner._worker(1)),
    ]

    runner.enqueued.add("doc-1")
    await runner.queue.put("doc-1")
    await asyncio.wait_for(processing.started.wait(), timeout=2)

    # Simulate a stale duplicate still sitting in the queue.
    runner.enqueued.add("doc-1")
    await runner.queue.put("doc-1")
    await asyncio.sleep(0.05)

    assert processing.runs == ["doc-1"]
    assert "doc-1" in runner.active
    assert "doc-1" in runner.pending_requeue

    processing.release.set()
    for _ in range(50):
        if len(processing.runs) >= 2:
            break
        await asyncio.sleep(0.02)

    assert processing.runs == ["doc-1", "doc-1"]
    await runner.stop()
