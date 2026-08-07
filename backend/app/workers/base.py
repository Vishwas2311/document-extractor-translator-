"""Worker-runner contract shared by local and future durable queue adapters."""

from typing import Protocol


class JobRunner(Protocol):
    concurrency: int

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def enqueue(self, document_id: str) -> None: ...
