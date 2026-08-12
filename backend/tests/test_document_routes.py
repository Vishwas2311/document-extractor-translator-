import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api.routes.documents import (
    create_financial_review,
    download_artifact,
    get_source,
    list_pages,
)
from app.core.auth import AuthPrincipal
from app.core.enums import FinancialPageDisposition
from app.core.exceptions import ConflictError, DocumentNotFoundError, InvalidDocumentError
from app.models.financial_review import FinancialReview
from app.schemas.financial import (
    FinancialCell,
    FinancialClassificationResult,
    FinancialPageClassification,
    FinancialResult,
    FinancialReviewCreate,
    FinancialTable,
    FinancialValidationIssue,
    FinancialValidationReport,
    NormalizedFinancialValue,
)
from app.schemas.page import PageMetadata, PageResult, TextBlock
from app.storage.local import LocalArtifactStorage


class PageRepository:
    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            page_count=2,
            pages_ready=2,
            status="needs_review",
            error_code=None,
            organization_id="org-local",
            owner_subject="synthetic-reviewer",
            assigned_reviewer_subject=None,
            document_review_status="needs_review",
        )


def _request(container: object) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    request = Request({"type": "http", "app": app, "headers": []})
    request.state.principal = AuthPrincipal(
        subject="synthetic-reviewer",
        token_fingerprint="tok-hash-only",
    )
    return request


class ReviewRepository:
    def __init__(self) -> None:
        self.persisted: list[FinancialReview] = []

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            status="needs_review",
            organization_id="org-local",
            owner_subject="synthetic-reviewer",
            assigned_reviewer_subject=None,
            document_review_status="needs_review",
            financial_result_sha256=None,
        )

    async def create_financial_review(self, review: FinancialReview) -> FinancialReview:
        review.id = f"review-{len(self.persisted) + 1}"
        self.persisted.append(review)
        return review


class DownloadRepository:
    def __init__(self, status: str) -> None:
        self.status = status

    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            status=self.status,
            error_code=None,
            original_filename="synthetic.pdf",
            organization_id="org-local",
            owner_subject="synthetic-reviewer",
            assigned_reviewer_subject=None,
            document_review_status="draft",
        )


class SourceRepository:
    async def get(self, document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=document_id,
            status="completed",
            stored_extension="pdf",
            content_type="application/pdf",
            original_filename="synthetic.pdf",
            error_code=None,
            organization_id="org-local",
            owner_subject="synthetic-reviewer",
            assigned_reviewer_subject=None,
            document_review_status="draft",
        )


async def test_get_source_returns_404_when_the_stored_file_is_missing(
    tmp_path: Path,
) -> None:
    document_id = "doc-missing-source"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    container = SimpleNamespace(repository=SourceRepository(), storage=storage)

    with pytest.raises(DocumentNotFoundError, match="Source document") as excinfo:
        await get_source(_request(container), document_id)

    assert excinfo.value.status_code == 404


async def test_get_source_serves_an_existing_file(tmp_path: Path) -> None:
    document_id = "doc-existing-source"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    storage.source_path(document_id, "pdf").write_bytes(b"%PDF-1.7 synthetic")
    container = SimpleNamespace(repository=SourceRepository(), storage=storage)

    response = await get_source(_request(container), document_id)

    assert Path(response.path) == storage.source_path(document_id, "pdf")


@pytest.mark.parametrize("document_status", ["failed", "cancelled"])
async def test_downloads_are_denied_for_unsuccessful_terminal_attempts(
    document_status: str,
) -> None:
    container = SimpleNamespace(
        repository=DownloadRepository(document_status),
        storage=SimpleNamespace(),
    )

    with pytest.raises(ConflictError, match="only after processing completes"):
        await download_artifact(
            _request(container),
            "doc-download-denied",
            "financial",
        )


async def test_list_pages_fallback_honors_financial_and_review_views(
    tmp_path: Path,
) -> None:
    document_id = "doc-page-filter"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    for page_number in (1, 2):
        page = PageResult(
            document_id=document_id,
            document_status="needs_review",
            page=PageMetadata(
                page_number=page_number,
                page_count=2,
                width=8.5,
                height=11,
                unit="inch",
            ),
            blocks=[
                TextBlock(
                    block_id=f"p{page_number}-b1",
                    reading_order=1,
                    source_text="Synthetic content",
                )
            ],
        )
        await storage.write_json(
            document_id,
            f"pages/page-{page_number:04d}.json",
            page.model_dump(mode="json"),
        )
    classification = FinancialClassificationResult(
        document_id=document_id,
        classifier_id="test",
        classifier_version="1",
        source_page_count=2,
        pages=[
            FinancialPageClassification(
                page_number=1,
                label="financial_table",
                confidence=0.6,
                disposition=FinancialPageDisposition.UNCERTAIN,
                selected=True,
                review_required=True,
                source="azure_custom_classifier",
            ),
            FinancialPageClassification(
                page_number=2,
                label="non_financial",
                confidence=0.99,
                disposition=FinancialPageDisposition.NON_FINANCIAL,
                selected=False,
                source="azure_custom_classifier",
            ),
        ],
    )
    await storage.write_json(
        document_id,
        "classification/pages.json",
        classification.model_dump(mode="json"),
    )
    container = SimpleNamespace(repository=PageRepository(), storage=storage)

    financial_response = await list_pages(
        _request(container), document_id, view="financial"
    )
    review_response = await list_pages(_request(container), document_id, view="review")

    financial = json.loads(bytes(financial_response.body))
    review = json.loads(bytes(review_response.body))
    assert [item["page_number"] for item in financial] == []
    assert [item["page_number"] for item in review] == [1]


async def test_list_pages_fallback_fails_closed_without_classification(
    tmp_path: Path,
) -> None:
    document_id = "doc-no-classification"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    page = PageResult(
        document_id=document_id,
        document_status="completed",
        page=PageMetadata(
            page_number=1,
            page_count=2,
            width=8.5,
            height=11,
            unit="inch",
        ),
    )
    await storage.write_json(
        document_id,
        "pages/page-0001.json",
        page.model_dump(mode="json"),
    )
    container = SimpleNamespace(repository=PageRepository(), storage=storage)

    financial_response = await list_pages(
        _request(container), document_id, view="financial"
    )
    review_response = await list_pages(_request(container), document_id, view="review")

    assert json.loads(bytes(financial_response.body)) == []
    assert json.loads(bytes(review_response.body)) == []


async def test_financial_approval_requires_and_persists_ambiguous_corrections(
    tmp_path: Path,
) -> None:
    document_id = "doc-review"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    result = FinancialResult(
        document_id=document_id,
        processing_version="prd-local-1",
        source_page_count=1,
        selected_pages=[1],
        tables=[
            FinancialTable(
                table_id="table-1",
                source_pages=[1],
                financial_type="financial_table",
                row_count=2,
                column_count=1,
                review_required=True,
                integrity_status="reconciled",
                reconciliation_candidate_id="candidate-1",
                cells=[
                    FinancialCell(
                        cell_id="cell-ambiguous",
                        row_index=0,
                        column_index=0,
                        source_page=1,
                        review_required=True,
                        value=NormalizedFinancialValue(
                            raw_text="12,34",
                            semantic_type="monetary_amount",
                            ambiguous=True,
                            requires_normalized_correction=True,
                            review_reason_code="ambiguous_monetary_separator",
                            normalization_status="ambiguous",
                        ),
                    ),
                    FinancialCell(
                        cell_id="cell-measurement",
                        row_index=1,
                        column_index=0,
                        source_page=1,
                        value=NormalizedFinancialValue(
                            raw_text="7.1",
                            semantic_type="measurement",
                            normalization_status="not_applicable",
                        ),
                    ),
                ],
            )
        ],
        reconciliation_candidate_ids=["candidate-1"],
        validation=FinancialValidationReport(
            document_id=document_id,
            issue_count=1,
            error_count=0,
            warning_count=1,
            review_required=True,
            issues=[
                FinancialValidationIssue(
                    issue_id="issue-1",
                    severity="warning",
                    code="ambiguous_monetary_format",
                    message="Synthetic ambiguous value.",
                    page_number=1,
                    table_id="table-1",
                    cell_id="cell-ambiguous",
                )
            ],
        ),
    )
    await storage.write_json(
        document_id,
        "normalized/financial.json",
        result.model_dump(mode="json"),
    )
    await storage.write_json(
        document_id,
        "manifest.json",
        {"artifacts": ["normalized/financial.json"]},
    )
    repository = ReviewRepository()
    container = SimpleNamespace(repository=repository, storage=storage)
    request = _request(container)
    request.state.principal = AuthPrincipal(
        subject="synthetic-reviewer",
        token_fingerprint="tok-hash-only",
    )

    with pytest.raises(InvalidDocumentError, match="only monetary cells"):
        await create_financial_review(
            request,
            document_id,
            FinancialReviewCreate(
                decision="rejected",
                corrections=[
                    {
                        "cell_id": "cell-measurement",
                        "normalized_value": Decimal("7.1"),
                        "reason": "This must not be accepted as a money correction.",
                    }
                ],
            ),
        )

    with pytest.raises(ConflictError, match="Every required monetary correction"):
        await create_financial_review(
            request,
            document_id,
            FinancialReviewCreate(decision="approved"),
        )

    corrected_review = FinancialReviewCreate(
        decision="approved",
        note="Confirmed against the synthetic source.",
        corrections=[
            {
                "cell_id": "cell-ambiguous",
                "normalized_value": Decimal("1234.00"),
                "currency": "EUR",
                "reason": "Reviewer confirmed thousands grouping.",
            }
        ],
    )
    with pytest.raises(ConflictError, match="Every reconstructed table structure"):
        await create_financial_review(request, document_id, corrected_review)

    persisted = await create_financial_review(
        request,
        document_id,
        FinancialReviewCreate.model_validate(
            {
                **corrected_review.model_dump(),
                "structure_decisions": [
                    {
                        "candidate_id": "candidate-1",
                        "decision": "accepted",
                        "reason": "Matched every row against the synthetic source.",
                    }
                ],
            }
        ),
    )

    assert persisted.decision == "approved"
    assert persisted.corrections[0].normalized_value == Decimal("1234.00")
    assert persisted.structure_decisions[0].candidate_id == "candidate-1"
    assert persisted.result_sha256 == repository.persisted[0].result_sha256
    assert persisted.reviewer_subject == "synthetic-reviewer:tok-hash-only"
    assert persisted.active_result
    assert len(persisted.result_sha256) == 64
