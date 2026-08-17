"""Idempotency store behavior for DocumentRepository.

Uses real SQLite transactions because the guarantee under test — that only one of
two concurrent identical requests may own a reservation — depends on a genuine
UNIQUE constraint and transactional isolation, not on any Python-level mock.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import update

from app.database.session import Database
from app.models.idempotency import IdempotencyRecord
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


async def test_clear_stale_idempotency_reservations_reclaims_only_orphaned_ones(
    tmp_path: Path,
) -> None:
    """Regression: an in-flight (response_status=0) reservation left behind by
    a crash/restart between reserve and complete/release had no TTL or sweep,
    permanently 409ing any future retry with that key. The sweep must delete
    only reservations old enough that no legitimate request could still own
    them, and must leave a fresh in-flight reservation untouched."""
    repository, database = await _new_repository(tmp_path)
    try:
        stale_scope = "org-1:user-1:document.upload:key-stale"
        fresh_scope = "org-1:user-1:document.upload:key-fresh"
        await repository.reserve_idempotency(stale_scope, "hash-1")
        await repository.reserve_idempotency(fresh_scope, "hash-2")

        # Backdate only the stale reservation past the sweep's cutoff.
        async with database.session_factory() as session:
            await session.execute(
                update(IdempotencyRecord)
                .where(IdempotencyRecord.scope == stale_scope)
                .values(created_at=datetime.now(UTC) - timedelta(seconds=7200))
            )
            await session.commit()

        cleared = await repository.clear_stale_idempotency_reservations(max_age_seconds=3600)
        assert cleared == 1

        # The stale key can now be freely re-reserved by a new request.
        owns_after_sweep, _ = await repository.reserve_idempotency(stale_scope, "hash-1")
        assert owns_after_sweep is True

        # The fresh reservation must have survived the sweep untouched.
        owns_fresh_again, fresh_record = await repository.reserve_idempotency(
            fresh_scope, "hash-2"
        )
        assert owns_fresh_again is False
        assert fresh_record.response_status == 0
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
