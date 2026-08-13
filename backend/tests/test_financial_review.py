"""Financial review apply + route persistence tests.

Regression coverage for the "reviewed financial export" gap: approving a
financial review previously only wrote an audit-log row and never produced a
downloadable export reflecting the reviewer's corrections, unlike translation
approval (which already regenerates exports/reviewed-bilingual-document.json).
Found via code review on 2026-08-13.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api.routes.documents import create_financial_review, download_artifact
from app.core.auth import AuthPrincipal
from app.core.exceptions import ConflictError
from app.core.versioning import CURRENT_PROCESSING_VERSION
from app.models.audit_event import AuditEvent
from app.models.financial_review import FinancialReview
from app.schemas.financial import (
    FinancialCell,
    FinancialResult,
    FinancialReviewCreate,
    FinancialTable,
    FinancialValidationReport,
    NormalizedFinancialValue,
)
from app.services.financial import (
    REVIEWED_FINANCIAL_CSV_PATH,
    REVIEWED_FINANCIAL_JSON_PATH,
    REVIEWED_FINANCIAL_XLSX_PATH,
    apply_financial_corrections,
    financial_result_sha256,
)
from app.storage.local import LocalArtifactStorage


def _financial_result(document_id: str) -> FinancialResult:
    return FinancialResult(
        document_id=document_id,
        processing_version=CURRENT_PROCESSING_VERSION,
        source_page_count=1,
        selected_pages=[1],
        validation=FinancialValidationReport(
            document_id=document_id,
            issue_count=0,
            error_count=0,
            warning_count=0,
            review_required=False,
        ),
        tables=[
            FinancialTable(
                table_id="t1",
                source_pages=[1],
                financial_type="statement",
                row_count=1,
                column_count=1,
                cells=[
                    FinancialCell(
                        cell_id="c1",
                        row_index=0,
                        column_index=0,
                        source_page=1,
                        review_required=True,
                        value=NormalizedFinancialValue(
                            raw_text="¥1,234.56",
                            value_type="amount",
                            semantic_type="monetary_amount",
                            currency="JPY",
                            currency_candidates=["JPY", "CNY"],
                            currency_source="symbol",
                            currency_ambiguous=True,
                            ambiguous=True,
                            requires_normalized_correction=True,
                            requires_currency_correction=True,
                            review_reason_code="ambiguous_currency",
                            normalization_status="ambiguous",
                        ),
                    )
                ],
            )
        ],
    )


def test_apply_financial_corrections_updates_cell_and_clears_flags() -> None:
    result = _financial_result("doc-1")
    correction = {
        "cell_id": "c1",
        "normalized_value": "1234.56",
        "currency": "CNY",
        "reason": "Confirmed with source page header",
    }
    review = FinancialReviewCreate(decision="approved", corrections=[correction])

    reviewed = apply_financial_corrections(result, review.corrections)

    cell = reviewed.tables[0].cells[0]
    assert cell.value.normalized_value == Decimal("1234.56")
    assert cell.value.currency == "CNY"
    assert cell.value.requires_normalized_correction is False
    assert cell.value.requires_currency_correction is False
    assert cell.warnings == ["Reviewer correction: Confirmed with source page header"]
    # The original result passed in must not be mutated - only the returned copy changes.
    assert result.tables[0].cells[0].value.currency == "JPY"
    assert result.tables[0].cells[0].value.requires_currency_correction is True


class _FinancialReviewRepository:
    def __init__(self, document: SimpleNamespace) -> None:
        self.document = document
        self.persisted: list[FinancialReview] = []
        self.audits: list[AuditEvent] = []

    async def get(self, document_id: str) -> SimpleNamespace:
        assert document_id == self.document.id
        return self.document

    async def create_financial_review(self, review: FinancialReview) -> FinancialReview:
        # Mirrors the real repository's hash binding: a review computed from a
        # drifted on-disk artifact must conflict with the stored column.
        if self.document.financial_result_sha256 != review.result_sha256:
            raise ConflictError(
                "The financial result changed before the review could be saved."
            )
        review.id = f"fr-{len(self.persisted) + 1}"
        self.persisted.append(review)
        self.document.financial_review_status = review.decision
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


def _document(document_id: str, stored_sha256: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        status="needs_review",
        processing_version=CURRENT_PROCESSING_VERSION,
        financial_result_sha256=stored_sha256,
        organization_id="org-local",
        owner_subject="reviewer-1",
        assigned_reviewer_subject=None,
        document_review_status="needs_review",
        financial_review_status=None,
        original_filename="sample.pdf",
        error_code=None,
    )


@pytest.mark.asyncio
async def test_approved_financial_review_writes_reviewed_exports(tmp_path: Path) -> None:
    document_id = "doc-financial-review"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    result = _financial_result(document_id)
    payload = result.model_dump(mode="json")
    await storage.write_json(document_id, "normalized/financial.json", payload)
    await storage.write_json(
        document_id, "manifest.json", {"artifacts": ["normalized/financial.json"]}
    )
    digest = financial_result_sha256(result)
    document = _document(document_id, stored_sha256=digest)
    repository = _FinancialReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    persisted = await create_financial_review(
        _request(container),
        document_id,
        FinancialReviewCreate(
            decision="approved",
            note="Confirmed currency with reviewer",
            corrections=[
                {
                    "cell_id": "c1",
                    "normalized_value": "1234.56",
                    "currency": "CNY",
                    "reason": "Confirmed with source page header",
                }
            ],
        ),
    )

    assert persisted.decision == "approved"
    assert persisted.active_result
    assert document.financial_review_status == "approved"

    assert storage.exists(document_id, REVIEWED_FINANCIAL_JSON_PATH)
    reviewed_json = await storage.read_json(document_id, REVIEWED_FINANCIAL_JSON_PATH)
    reviewed_cell = reviewed_json["tables"][0]["cells"][0]
    assert reviewed_cell["value"]["normalized_value"] == "1234.56"
    assert reviewed_cell["value"]["currency"] == "CNY"

    assert storage.exists(document_id, REVIEWED_FINANCIAL_CSV_PATH)
    assert storage.exists(document_id, REVIEWED_FINANCIAL_XLSX_PATH)
    assert repository.audits and repository.audits[0].action == "financial.review.approved"

    downloaded_json = await download_artifact(
        _request(container), document_id, "reviewed-financial"
    )
    assert Path(downloaded_json.path).name.endswith("reviewed-financial-document.json")
    downloaded_csv = await download_artifact(
        _request(container), document_id, "reviewed-financial-csv"
    )
    assert Path(downloaded_csv.path).name.endswith("reviewed-financial-document.csv")
    downloaded_xlsx = await download_artifact(
        _request(container), document_id, "reviewed-financial-xlsx"
    )
    assert Path(downloaded_xlsx.path).name.endswith("reviewed-financial-document.xlsx")


@pytest.mark.asyncio
async def test_reviewed_financial_download_blocked_before_approval(tmp_path: Path) -> None:
    document_id = "doc-financial-unapproved"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    result = _financial_result(document_id)
    await storage.write_json(
        document_id, "normalized/financial.json", result.model_dump(mode="json")
    )
    await storage.write_json(document_id, "manifest.json", {"artifacts": []})
    document = _document(document_id, stored_sha256=financial_result_sha256(result))
    repository = _FinancialReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    with pytest.raises(ConflictError, match="only after financial approval"):
        await download_artifact(_request(container), document_id, "reviewed-financial")


@pytest.mark.asyncio
async def test_rejected_financial_review_writes_no_reviewed_exports(tmp_path: Path) -> None:
    document_id = "doc-financial-rejected"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    result = _financial_result(document_id)
    await storage.write_json(
        document_id, "normalized/financial.json", result.model_dump(mode="json")
    )
    await storage.write_json(
        document_id, "manifest.json", {"artifacts": ["normalized/financial.json"]}
    )
    document = _document(document_id, stored_sha256=financial_result_sha256(result))
    repository = _FinancialReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    persisted = await create_financial_review(
        _request(container),
        document_id,
        FinancialReviewCreate(decision="rejected", note="Needs rework"),
    )

    assert persisted.decision == "rejected"
    assert repository.persisted
    assert not storage.exists(document_id, REVIEWED_FINANCIAL_JSON_PATH)
    assert not storage.exists(document_id, REVIEWED_FINANCIAL_CSV_PATH)
    assert not storage.exists(document_id, REVIEWED_FINANCIAL_XLSX_PATH)


@pytest.mark.asyncio
async def test_financial_review_conflicts_when_stored_hash_differs_from_artifact(
    tmp_path: Path,
) -> None:
    document_id = "doc-financial-hash-drift"
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    storage.ensure_document_dirs(document_id)
    result = _financial_result(document_id)
    await storage.write_json(
        document_id, "normalized/financial.json", result.model_dump(mode="json")
    )
    await storage.write_json(
        document_id, "manifest.json", {"artifacts": ["normalized/financial.json"]}
    )
    document = _document(document_id, stored_sha256="f" * 64)
    repository = _FinancialReviewRepository(document)
    container = SimpleNamespace(repository=repository, storage=storage)

    with pytest.raises(ConflictError, match="changed before the review") as excinfo:
        await create_financial_review(
            _request(container),
            document_id,
            FinancialReviewCreate(decision="rejected", note="Checking drift"),
        )

    assert excinfo.value.status_code == 409
    assert repository.persisted == []
    assert not storage.exists(document_id, REVIEWED_FINANCIAL_JSON_PATH)
