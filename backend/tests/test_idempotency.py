"""Idempotency store behavior for DocumentRepository.

Uses real SQLite transactions because the guarantee under test — that only one of
two concurrent identical requests may own a reservation — depends on a genuine
UNIQUE constraint and transactional isolation, not on any Python-level mock.
"""

import asyncio
from pathlib import Path

from app.database.session import Database
from app.repositories.documents import DocumentRepository


async def _new_repository(tmp_path: Path) -> tuple[DocumentRepository, Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'idem.db'}")
    await database.create_schema()
    return DocumentRepository(database.session_factory), database


async def test_reserve_then_complete_replays_response(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        scope = "org-1:user-1:document.upload:key-abc"
        owns, record = await repository.reserve_idempotency(scope, "hash-1")
        assert owns is True
        assert record.response_status == 0

        await repository.complete_idempotency(
            scope,
            response_status=202,
            response_body='{"document_id": "doc-1"}',
            resource_id="doc-1",
        )

        owns_again, replay = await repository.reserve_idempotency(scope, "hash-1")
        assert owns_again is False
        assert replay.response_status == 202
        assert replay.response_body == '{"document_id": "doc-1"}'
        assert replay.resource_id == "doc-1"
    finally:
        await database.dispose()


async def test_reserve_is_exclusive_under_concurrency(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        scope = "org-1:user-1:document.upload:key-concurrent"
        first, second = await asyncio.gather(
            repository.reserve_idempotency(scope, "hash-1"),
            repository.reserve_idempotency(scope, "hash-1"),
        )
        owners = [owns for owns, _ in (first, second)]
        assert owners.count(True) == 1
        assert owners.count(False) == 1
    finally:
        await database.dispose()


async def test_release_allows_retry_after_failure(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        scope = "org-1:user-1:document.upload:key-fail"
        owns, _ = await repository.reserve_idempotency(scope, "hash-1")
        assert owns is True

        # Work failed before completion — the reservation is dropped.
        await repository.release_idempotency(scope)

        owns_after, record = await repository.reserve_idempotency(scope, "hash-1")
        assert owns_after is True
        assert record.response_status == 0
    finally:
        await database.dispose()


async def test_completed_reservation_is_not_released(tmp_path: Path) -> None:
    repository, database = await _new_repository(tmp_path)
    try:
        scope = "org-1:user-1:document.upload:key-done"
        await repository.reserve_idempotency(scope, "hash-1")
        await repository.complete_idempotency(
            scope, response_status=202, response_body="{}", resource_id="doc-1"
        )

        # A late release must never erase a completed response.
        await repository.release_idempotency(scope)

        owns, record = await repository.reserve_idempotency(scope, "hash-1")
        assert owns is False
        assert record.response_status == 202
    finally:
        await database.dispose()
