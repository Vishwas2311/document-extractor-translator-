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
