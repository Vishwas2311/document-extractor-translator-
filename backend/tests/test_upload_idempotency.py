"""Regression: the upload route's Idempotency-Key fingerprint must cover the
actual uploaded bytes, not just filename/content-type/data-class/profile.

Before this fix, request_fingerprint() was built from metadata alone. A
client replaying the same Idempotency-Key with a genuinely different file
(same filename and content-type - e.g. a corrected version of the same
document) fingerprinted identically to the first request, so the second
upload was silently discarded and the *first* document's cached response
was returned instead - contradicting the documented contract that a repeated
key with a different body is rejected.

Confirmed by code review on 2026-08-12.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import UploadFile
from starlette.requests import Request

from app.api.routes.documents import upload_document
from app.core.authorization import AuthPrincipal
from app.core.exceptions import ConflictError


class FakeIdempotencyRepository:
    """Minimal in-memory stand-in for the reserve/complete/release contract
    DocumentRepository implements - enough to exercise the route's fingerprint
    logic without a real database."""

    def __init__(self) -> None:
        self._records: dict[str, SimpleNamespace] = {}
        self.create_upload_calls = 0

    async def reserve_idempotency(
        self, scope: str, fingerprint: str
    ) -> tuple[bool, SimpleNamespace | None]:
        existing = self._records.get(scope)
        if existing is None:
            self._records[scope] = SimpleNamespace(
                request_hash=fingerprint, response_status=0, response_body=None
            )
            return True, None
        return False, existing

    async def complete_idempotency(
        self, scope: str, *, response_status: int, response_body: str, resource_id: str
    ) -> None:
        record = self._records[scope]
        record.response_status = response_status
        record.response_body = response_body

    async def release_idempotency(self, scope: str) -> None:
        self._records.pop(scope, None)

    async def create_audit_event(self, event: Any) -> Any:
        return event


class FakeDocumentService:
    def __init__(self) -> None:
        self.calls = 0

    async def create_upload(self, upload: UploadFile, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            id=f"doc-{self.calls}",
            status="queued",
            processing_profile="GENAI_PSEUDONYMIZED",
            data_class="synthetic",
        )


def _request(container: object, principal: AuthPrincipal) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    request = Request({"type": "http", "app": app, "headers": [(b"idempotency-key", b"key-1")]})
    request.state.principal = principal
    return request


def _container(
    repository: FakeIdempotencyRepository, document_service: FakeDocumentService
) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(app_env="development", api_v1_prefix="/api/v1"),
        repository=repository,
        document_service=document_service,
        runner=SimpleNamespace(enqueue=_noop_enqueue),
    )


async def _noop_enqueue(_document_id: str) -> None:
    return None


async def test_same_idempotency_key_with_different_file_is_rejected() -> None:
    repository = FakeIdempotencyRepository()
    document_service = FakeDocumentService()
    container = _container(repository, document_service)
    principal = AuthPrincipal(subject="tester", token_fingerprint="tok-hash")

    first = UploadFile(filename="intake.pdf", file=io.BytesIO(b"%PDF-1.7 first version"))
    response_one = await upload_document(_request(container, principal), first)
    assert response_one.document_id == "doc-1"
    assert document_service.calls == 1

    # Same Idempotency-Key, same filename/content-type, genuinely different bytes.
    second = UploadFile(filename="intake.pdf", file=io.BytesIO(b"%PDF-1.7 corrected version"))
    with pytest.raises(ConflictError, match="already used with a different request"):
        await upload_document(_request(container, principal), second)

    # The second, different file must never have been processed as a silent duplicate.
    assert document_service.calls == 1


async def test_same_idempotency_key_with_identical_file_replays_cached_response() -> None:
    repository = FakeIdempotencyRepository()
    document_service = FakeDocumentService()
    container = _container(repository, document_service)
    principal = AuthPrincipal(subject="tester", token_fingerprint="tok-hash")

    payload = b"%PDF-1.7 identical bytes"
    first = UploadFile(filename="intake.pdf", file=io.BytesIO(payload))
    response_one = await upload_document(_request(container, principal), first)

    second = UploadFile(filename="intake.pdf", file=io.BytesIO(payload))
    response_two = await upload_document(_request(container, principal), second)

    assert response_two.document_id == response_one.document_id
    assert document_service.calls == 1  # replayed, not reprocessed
