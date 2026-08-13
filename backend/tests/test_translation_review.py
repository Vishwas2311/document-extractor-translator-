"""Translation review apply/validate + route persistence smoke tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api.routes.documents import create_translation_review, download_artifact
from app.core.auth import AuthPrincipal
from app.core.exceptions import ConflictError
from app.core.versioning import CURRENT_PROCESSING_VERSION
from app.models.audit_event import AuditEvent
from app.models.translation_review import TranslationReview
from app.schemas.translation_review import TranslationReviewCreate
from app.services.translation_review import (
    REVIEWED_BILINGUAL_PATH,
    apply_translation_corrections,
    bilingual_result_sha256,
    validate_translation_approval,
)
from app.storage.local import LocalArtifactStorage


def test_apply_corrections_clears_review_flags() -> None:
    bilingual = {
        "blocks": [
            {
                "block_id": "b1",
                "translated_text": "Machine text",
                "review_required": True,
                "warnings": [],
            }
        ],
        "tables": [],
    }
    review = TranslationReviewCreate(
        decision="approved",
        corrections=[
            {
                "target_kind": "block",
                "target_id": "b1",
                "page_number": 1,
                "corrected_translated_text": "Human text",
                "reason": "Improved phrasing",
            }
        ],
    )
    validate_translation_approval(bilingual, review)
    reviewed = apply_translation_corrections(bilingual, review.corrections)
    assert reviewed["blocks"][0]["translated_text"] == "Human text"
    assert reviewed["blocks"][0]["review_required"] is False


def test_approval_blocked_when_flags_remain() -> None:
    bilingual = {
        "blocks": [
            {"block_id": "b1", "translated_text": "A", "review_required": True},
            {"block_id": "b2", "translated_text": "B", "review_required": True},
        ],
        "tables": [],
    }
    review = TranslationReviewCreate(
        decision="approved",
        corrections=[
            {
                "target_kind": "block",
                "target_id": "b1",
                "page_number": 1,
                "corrected_translated_text": "Fixed",
                "reason": "Partial",
            }
        ],
    )
    with pytest.raises(ConflictError, match="Every review-required"):
        validate_translation_approval(bilingual, review)


class _TranslationReviewRepository:
    def __init__(self, document: SimpleNamespace) -> None:
        self.document = document
        self.persisted: list[TranslationReview] = []
        self.audits: list[AuditEvent] = []

    async def get(self, document_id: str) -> SimpleNamespace:
        assert document_id == self.document.id
        return self.document

    async def update_document(self, document_id: str, **values: object) -> None:
        for key, value in values.items():
            setattr(self.document, key, value)

    async def create_translation_review(self, review: TranslationReview) -> TranslationReview:
        # Mirrors the real repository's hash binding: a review computed from a
        # drifted on-disk artifact must conflict with the stored column.
        if self.document.translation_result_sha256 != review.result_sha256:
            raise ConflictError(
                "The translation result changed before the review could be saved."
            )
        review.id = f"tr-{len(self.persisted) + 1}"
        self.persisted.append(review)
        self.document.translation_review_status = review.decision
        self.document.document_review_status = (
            "approved" if review.decision == "approved" else "rejected"
        )
        return review

    async def create_audit_event(self, event: AuditEvent) -> AuditEvent:
        event.id = f"audit-{len(self.audits) + 1}"
        self.audits.append(event)
        return event


def _request(container: object) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    request = Request({"type": "http", "app": app, "headers": []})
    request.state.principal = AuthPrincipal(
        subject="reviewer-1",
        token_fingerprint="tok-rev",
    )
    return request


@pytest.mark.asyncio
async def test_translation_review_route_writes_approved_export(tmp_path: Path) -> None:
    document_id = "doc-translation-review"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    bilingual = {
        "document_id": document_id,
        "blocks": [
            {
                "block_id": "b1",
                "translated_text": "Machine",
                "review_required": True,
                "warnings": [],
            }
        ],
        "tables": [],
    }
    await storage.write_json(document_id, "exports/bilingual-document.json", bilingual)
    await storage.write_json(document_id, "manifest.json", {"artifacts": []})
    digest = bilingual_result_sha256(bilingual)
    document = SimpleNamespace(
        id=document_id,
        status="needs_review",
        processing_version=CURRENT_PROCESSING_VERSION,
        translation_result_sha256=digest,
        organization_id="org-local",
        owner_subject="reviewer-1",
        assigned_reviewer_subject=None,
        document_review_status="needs_review",
        original_filename="sample.pdf",
        error_code=None,
    )
    repository = _TranslationReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    persisted = await create_translation_review(
        _request(container),
        document_id,
        TranslationReviewCreate(
            decision="approved",
            note="Looks good",
            corrections=[
                {
                    "target_kind": "block",
                    "target_id": "b1",
                    "page_number": 1,
                    "corrected_translated_text": "Approved English",
                    "reason": "Clarity",
                }
            ],
        ),
    )

    assert persisted.decision == "approved"
    assert persisted.active_result
    assert document.document_review_status == "approved"
    assert storage.exists(document_id, REVIEWED_BILINGUAL_PATH)
    reviewed = await storage.read_json(document_id, REVIEWED_BILINGUAL_PATH)
    assert reviewed["blocks"][0]["translated_text"] == "Approved English"
    assert repository.audits and repository.audits[0].action == "translation.review.approved"

    downloaded = await download_artifact(
        _request(container),
        document_id,
        "reviewed-bilingual",
    )
    assert Path(downloaded.path).name.endswith("reviewed-bilingual-document.json")


def _bilingual_fixture(document_id: str, *, review_required: bool = False) -> dict[str, object]:
    return {
        "document_id": document_id,
        "blocks": [
            {
                "block_id": "b1",
                "translated_text": "Machine",
                "review_required": review_required,
                "warnings": [],
            }
        ],
        "tables": [],
    }


def _document(document_id: str, stored_sha256: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        status="needs_review",
        processing_version=CURRENT_PROCESSING_VERSION,
        translation_result_sha256=stored_sha256,
        organization_id="org-local",
        owner_subject="reviewer-1",
        assigned_reviewer_subject=None,
        document_review_status="needs_review",
        original_filename="sample.pdf",
        error_code=None,
    )


@pytest.mark.asyncio
async def test_approved_translation_review_not_committed_when_export_write_fails(
    tmp_path: Path,
) -> None:
    """Regression: the review record must not be persisted if writing the
    reviewed bilingual export fails - otherwise the document is stuck
    permanently "approved" with a missing download. Writing the export before
    the DB commit (this session's fix) means a write failure here must leave
    the document's review status and the review audit trail untouched."""
    document_id = "doc-translation-write-fails"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    bilingual = _bilingual_fixture(document_id, review_required=True)
    await storage.write_json(document_id, "exports/bilingual-document.json", bilingual)
    document = _document(document_id, stored_sha256=bilingual_result_sha256(bilingual))
    repository = _TranslationReviewRepository(document)

    class _FailingStorage(LocalArtifactStorage):
        async def write_json(
            self, document_id: str, relative_path: str, payload: dict[str, object]
        ) -> Path:
            if relative_path == REVIEWED_BILINGUAL_PATH:
                raise OSError("simulated disk failure writing reviewed bilingual export")
            return await super().write_json(document_id, relative_path, payload)

    failing_storage = _FailingStorage(tmp_path / "artifacts")
    container = SimpleNamespace(repository=repository, storage=failing_storage)

    with pytest.raises(OSError, match="simulated disk failure"):
        await create_translation_review(
            _request(container),
            document_id,
            TranslationReviewCreate(
                decision="approved",
                note="Should not commit",
                corrections=[
                    {
                        "target_kind": "block",
                        "target_id": "b1",
                        "page_number": 1,
                        "corrected_translated_text": "Approved English",
                        "reason": "Clarity",
                    }
                ],
            ),
        )

    assert document.document_review_status == "needs_review"
    assert repository.persisted == []


@pytest.mark.asyncio
async def test_translation_review_conflicts_when_stored_hash_differs_from_artifact(
    tmp_path: Path,
) -> None:
    """DB-vs-disk drift: the stored translation_result_sha256 no longer matches
    the bilingual artifact on disk. The review must be rejected with a 409 and
    must not write a reviewed artifact."""
    document_id = "doc-hash-drift"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    await storage.write_json(
        document_id, "exports/bilingual-document.json", _bilingual_fixture(document_id)
    )
    document = _document(document_id, stored_sha256="f" * 64)
    repository = _TranslationReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    with pytest.raises(ConflictError, match="changed before the review") as excinfo:
        await create_translation_review(
            _request(container),
            document_id,
            TranslationReviewCreate(decision="rejected", note="Checking drift"),
        )

    assert excinfo.value.status_code == 409
    assert repository.persisted == []
    # A failed review record must leave no reviewed artifact behind.
    assert not storage.exists(document_id, REVIEWED_BILINGUAL_PATH)


@pytest.mark.asyncio
async def test_rejected_translation_review_writes_no_reviewed_artifact(
    tmp_path: Path,
) -> None:
    document_id = "doc-rejected-review"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    bilingual = _bilingual_fixture(document_id)
    await storage.write_json(document_id, "exports/bilingual-document.json", bilingual)
    document = _document(document_id, stored_sha256=bilingual_result_sha256(bilingual))
    repository = _TranslationReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    persisted = await create_translation_review(
        _request(container),
        document_id,
        TranslationReviewCreate(decision="rejected", note="Needs rework"),
    )

    assert persisted.decision == "rejected"
    assert repository.persisted
    # Only approvals materialize the reviewed export.
    assert not storage.exists(document_id, REVIEWED_BILINGUAL_PATH)


@pytest.mark.asyncio
async def test_translation_review_backfills_a_missing_stored_hash(
    tmp_path: Path,
) -> None:
    document_id = "doc-backfill-hash"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    bilingual = _bilingual_fixture(document_id)
    await storage.write_json(document_id, "exports/bilingual-document.json", bilingual)
    document = _document(document_id, stored_sha256=None)
    repository = _TranslationReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    persisted = await create_translation_review(
        _request(container),
        document_id,
        TranslationReviewCreate(decision="rejected", note="First review"),
    )

    assert persisted.result_sha256 == bilingual_result_sha256(bilingual)
    assert document.translation_result_sha256 == persisted.result_sha256
