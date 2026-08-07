import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.auth import AuthPrincipal, require_principal
from app.core.authorization import require_document_access
from app.core.enums import (
    TERMINAL_DOCUMENT_STATUSES,
    DocumentStatus,
    FinancialPageDisposition,
    RetryMode,
)
from app.core.exceptions import ConflictError, DocumentNotFoundError, InvalidDocumentError
from app.dependencies.services import ServiceContainer
from app.models.document import Document
from app.models.financial_review import FinancialReview
from app.models.translation_review import TranslationReview
from app.schemas.document import (
    CancelDocumentResponse,
    DocumentCreateResponse,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    PageSummary,
)
from app.schemas.financial import (
    FinancialClassificationResult,
    FinancialResult,
    FinancialReviewCreate,
    FinancialReviewHistory,
    FinancialReviewRecord,
    FinancialValidationReport,
)
from app.schemas.page import PageResult
from app.schemas.table_reconciliation import TableReconciliationResult
from app.schemas.translation_review import (
    TranslationReviewCreate,
    TranslationReviewHistory,
    TranslationReviewRecord,
)
from app.services.audit import AuditService
from app.services.financial import financial_result_sha256
from app.services.translation_review import (
    REVIEWED_BILINGUAL_PATH,
    TRANSLATION_REVIEW_SCHEMA_VERSION,
    apply_translation_corrections,
    bilingual_result_sha256,
    validate_translation_approval,
)

router = APIRouter(dependencies=[Depends(require_principal)])

NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, private", "Pragma": "no-cache"}


def container(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.container)


def _principal(request: Request) -> AuthPrincipal:
    return cast(AuthPrincipal, request.state.principal)


def _enforce_document_access(
    principal: AuthPrincipal,
    document: Document,
    *,
    action: str = "read",
) -> None:
    require_document_access(
        principal,
        organization_id=getattr(document, "organization_id", "org-local"),
        owner_subject=getattr(document, "owner_subject", "local-api-token"),
        assigned_reviewer_subject=getattr(document, "assigned_reviewer_subject", None),
        document_review_status=getattr(document, "document_review_status", None),
        action=action,
    )


async def _require_current_artifact(
    services: ServiceContainer,
    document: Document,
    relative_path: str,
    unavailable_message: str,
) -> None:
    document_status = DocumentStatus(document.status)
    if document_status not in {DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW}:
        raise DocumentNotFoundError(unavailable_message)
    if not services.storage.exists(document.id, "manifest.json"):
        raise DocumentNotFoundError(unavailable_message)
    manifest = await services.storage.read_json(document.id, "manifest.json")
    if relative_path not in {
        item for item in manifest.get("artifacts", []) if isinstance(item, str)
    }:
        raise DocumentNotFoundError(unavailable_message)


@router.post("", response_model=DocumentCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    data_class: Annotated[str | None, Form()] = None,
    processing_profile: Annotated[str | None, Form()] = None,
) -> DocumentCreateResponse:
    services = container(request)
    principal = _principal(request)
    document = await services.document_service.create_upload(
        file,
        data_class=data_class,
        processing_profile=processing_profile,
        owner_subject=principal.subject,
        organization_id=principal.organization_id,
    )
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
    )
    await services.runner.enqueue(document.id)
    return DocumentCreateResponse(
        document_id=document.id,
        status=document.status,
        status_url=f"{services.settings.api_v1_prefix}/documents/{document.id}",
        processing_profile=document.processing_profile,
        data_class=document.data_class,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DocumentListResponse:
    items, total = await container(request).repository.list(
        page, page_size, principal=_principal(request)
    )
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    payload = DocumentDetail.model_validate(document).model_dump(mode="json")
    if DocumentStatus(document.status) not in TERMINAL_DOCUMENT_STATUSES:
        metrics = await services.repository.queue_metrics(document_id)
        payload["queue_position"] = metrics.get("queue_position")
        payload["active_jobs"] = metrics.get("active_jobs")
        payload["worker_slots"] = services.runner.concurrency
    return JSONResponse(payload, headers=NO_STORE)


@router.get("/{document_id}/source")
async def get_source(request: Request, document_id: str) -> FileResponse:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    source = services.storage.source_path(document_id, document.stored_extension)
    return FileResponse(
        source,
        media_type=document.content_type,
        filename=document.original_filename,
        content_disposition_type="inline",
        headers=NO_STORE,
    )


@router.get("/{document_id}/pages", response_model=list[PageSummary])
async def list_pages(
    request: Request,
    document_id: str,
    view: Literal["all", "financial", "review"] = Query(default="all"),
) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    if getattr(document, "error_code", None) == "reprocess_cleanup_failed":
        return JSONResponse([], headers=NO_STORE)
    if document.status == DocumentStatus.QUEUED.value and not document.pages_ready:
        return JSONResponse([], headers=NO_STORE)
    if document.page_count is None:
        return JSONResponse([], headers=NO_STORE)

    index_path = "pages/index.json"
    if services.storage.exists(document_id, index_path):
        index = await services.storage.read_json(document_id, index_path)
        summary_payloads = [
            PageSummary.model_validate(item).model_dump(mode="json")
            for item in index.get("pages", [])
            if isinstance(item, dict)
            and 1 <= int(item.get("page_number", 0)) <= int(document.page_count)
            and (
                view == "all"
                or (
                    view == "financial"
                    and item.get("financial_disposition") == "financial"
                )
                or (view == "review" and bool(item.get("review_required", False)))
            )
        ]
        return JSONResponse(summary_payloads, headers=NO_STORE)

    classification_by_page = {}
    if services.storage.exists(document_id, "classification/pages.json"):
        classification_payload = await services.storage.read_json(
            document_id, "classification/pages.json"
        )
        classification = FinancialClassificationResult.model_validate(
            classification_payload
        )
        classification_by_page = {
            page.page_number: page for page in classification.pages
        }

    summaries: list[PageSummary] = []
    for number in range(1, document.page_count + 1):
        relative = f"pages/page-{number:04d}.json"
        if not services.storage.exists(document_id, relative):
            continue
        payload = PageResult.model_validate(await services.storage.read_json(document_id, relative))
        financial_page = classification_by_page.get(number)
        review_required = (
            bool(payload.warnings)
            or any(block.review_required for block in payload.blocks)
            or any(cell.review_required for table in payload.tables for cell in table.cells)
            or bool(financial_page and financial_page.review_required)
        )
        if view == "financial" and not bool(
            financial_page
            and financial_page.disposition == FinancialPageDisposition.FINANCIAL
        ):
            continue
        if view == "review" and not review_required:
            continue
        summaries.append(
            PageSummary(
                page_number=number,
                width=payload.page.width,
                height=payload.page.height,
                unit=payload.page.unit,
                angle=payload.page.angle,
                block_count=len(payload.blocks),
                table_count=len(payload.tables),
                review_required=review_required,
                financial_label=financial_page.label if financial_page else None,
                financial_confidence=financial_page.confidence if financial_page else None,
                financial_disposition=financial_page.disposition if financial_page else None,
                financial_selected=bool(financial_page and financial_page.selected),
                financial_reason=financial_page.reasons if financial_page else [],
            )
        )
    return JSONResponse(
        [item.model_dump(mode="json") for item in summaries],
        headers=NO_STORE,
    )


@router.get(
    "/{document_id}/classification",
    response_model=FinancialClassificationResult,
)
async def get_financial_classification(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    await _require_current_artifact(
        services,
        document,
        "classification/pages.json",
        "Financial page classification is not available.",
    )
    if not services.storage.exists(document_id, "classification/pages.json"):
        raise DocumentNotFoundError("Financial page classification is not available.")
    payload = await services.storage.read_json(document_id, "classification/pages.json")
    result = FinancialClassificationResult.model_validate(payload)
    return JSONResponse(result.model_dump(mode="json"), headers=NO_STORE)


@router.get("/{document_id}/financial-result", response_model=FinancialResult)
async def get_financial_result(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    await _require_current_artifact(
        services,
        document,
        "normalized/financial.json",
        "Financial extraction is not available.",
    )
    if not services.storage.exists(document_id, "normalized/financial.json"):
        raise DocumentNotFoundError("Financial extraction is not available.")
    payload = await services.storage.read_json(document_id, "normalized/financial.json")
    result = FinancialResult.model_validate(payload)
    return JSONResponse(result.model_dump(mode="json"), headers=NO_STORE)


@router.get(
    "/{document_id}/table-reconciliation",
    response_model=TableReconciliationResult,
)
async def get_table_reconciliation(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    relative_path = "normalized/table-reconciliation.json"
    await _require_current_artifact(
        services,
        document,
        relative_path,
        "Table reconciliation evidence is not available.",
    )
    payload = await services.storage.read_json(document_id, relative_path)
    result = TableReconciliationResult.model_validate(payload)
    return JSONResponse(result.model_dump(mode="json"), headers=NO_STORE)


@router.get(
    "/{document_id}/financial-validation",
    response_model=FinancialValidationReport,
)
async def get_financial_validation(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    await _require_current_artifact(
        services,
        document,
        "validation/financial.json",
        "Financial validation is not available.",
    )
    if not services.storage.exists(document_id, "validation/financial.json"):
        raise DocumentNotFoundError("Financial validation is not available.")
    payload = await services.storage.read_json(document_id, "validation/financial.json")
    result = FinancialValidationReport.model_validate(payload)
    return JSONResponse(result.model_dump(mode="json"), headers=NO_STORE)


@router.get(
    "/{document_id}/financial-reviews",
    response_model=FinancialReviewHistory,
)
async def get_financial_reviews(
    request: Request,
    document_id: str,
) -> FinancialReviewHistory:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    reviews = await services.repository.financial_reviews(document_id)
    return FinancialReviewHistory(
        items=[
            FinancialReviewRecord.model_validate(review).model_copy(
                update={
                    "active_result": bool(document.financial_result_sha256)
                    and review.result_sha256 == document.financial_result_sha256
                }
            )
            for review in reviews
        ]
    )


@router.post(
    "/{document_id}/financial-reviews",
    response_model=FinancialReviewRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_financial_review(
    request: Request,
    document_id: str,
    review: FinancialReviewCreate,
) -> FinancialReviewRecord:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document, action="review")
    if DocumentStatus(document.status) not in {
        DocumentStatus.COMPLETED,
        DocumentStatus.NEEDS_REVIEW,
    }:
        raise ConflictError("Financial review is available only after processing completes.")
    await _require_current_artifact(
        services,
        document,
        "normalized/financial.json",
        "Financial extraction is not available.",
    )

    payload = await services.storage.read_json(document_id, "normalized/financial.json")
    result = FinancialResult.model_validate(payload)
    result_sha256 = financial_result_sha256(result)
    cells = {cell.cell_id: cell for table in result.tables for cell in table.cells}
    corrections_by_cell = {
        correction.cell_id: correction for correction in review.corrections
    }
    correction_ids = set(corrections_by_cell)
    unknown_ids = correction_ids - set(cells)
    if unknown_ids:
        raise InvalidDocumentError(
            "Financial corrections reference cells that are not in the active result."
        )
    correctable_ids = {
        cell.cell_id
        for cell in cells.values()
        if cell.value.requires_normalized_correction
        or cell.value.requires_currency_correction
    }
    ineligible_ids = correction_ids - correctable_ids
    if ineligible_ids:
        raise InvalidDocumentError(
            "Financial corrections may target only monetary cells marked for correction."
        )
    structure_by_candidate = {
        item.candidate_id: item for item in review.structure_decisions
    }
    required_candidates = set(result.reconciliation_candidate_ids)
    unknown_candidates = set(structure_by_candidate) - required_candidates
    if unknown_candidates:
        raise InvalidDocumentError(
            "Financial review references reconstruction candidates that are not active."
        )

    if review.decision == "approved":
        if result.validation.error_count:
            raise ConflictError(
                "A financial result with validation errors cannot be approved."
            )
        unresolved = {
            cell.cell_id
            for cell in cells.values()
            if (
                cell.value.requires_normalized_correction
                or cell.value.requires_currency_correction
            )
            and (
                cell.cell_id not in correction_ids
                or (
                    cell.value.requires_normalized_correction
                    and corrections_by_cell[cell.cell_id].normalized_value is None
                )
                or (
                    cell.value.requires_currency_correction
                    and corrections_by_cell[cell.cell_id].currency is None
                )
            )
        }
        if unresolved:
            raise ConflictError(
                "Every required monetary correction must be resolved before approval."
            )
        unresolved_structure = {
            candidate_id
            for candidate_id in required_candidates
            if candidate_id not in structure_by_candidate
            or structure_by_candidate[candidate_id].decision != "accepted"
        }
        if unresolved_structure:
            raise ConflictError(
                "Every reconstructed table structure must be accepted before approval."
            )

    principal = cast(AuthPrincipal, request.state.principal)
    now = datetime.now(UTC)
    persisted = await services.repository.create_financial_review(
        FinancialReview(
            document_id=document_id,
            decision=review.decision,
            reviewer_subject=f"{principal.subject}:{principal.token_fingerprint}",
            note=review.note,
            corrections=[
                correction.model_dump(mode="json") for correction in review.corrections
            ],
            structure_decisions=[
                item.model_dump(mode="json") for item in review.structure_decisions
            ],
            processing_version=result.processing_version,
            result_schema_version=result.schema_version,
            result_sha256=result_sha256,
            created_at=now,
        )
    )
    return FinancialReviewRecord.model_validate(persisted).model_copy(
        update={"active_result": True}
    )


@router.get(
    "/{document_id}/translation-reviews",
    response_model=TranslationReviewHistory,
)
async def get_translation_reviews(
    request: Request,
    document_id: str,
) -> TranslationReviewHistory:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    reviews = await services.repository.translation_reviews(document_id)
    return TranslationReviewHistory(
        items=[
            TranslationReviewRecord.model_validate(review).model_copy(
                update={
                    "active_result": bool(document.translation_result_sha256)
                    and review.result_sha256 == document.translation_result_sha256
                }
            )
            for review in reviews
        ]
    )


@router.post(
    "/{document_id}/translation-reviews",
    response_model=TranslationReviewRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_translation_review(
    request: Request,
    document_id: str,
    review: TranslationReviewCreate,
) -> TranslationReviewRecord:
    services = container(request)
    document = await services.repository.get(document_id)
    principal = _principal(request)
    _enforce_document_access(principal, document, action="review")
    if DocumentStatus(document.status) not in {
        DocumentStatus.COMPLETED,
        DocumentStatus.NEEDS_REVIEW,
    }:
        raise ConflictError("Translation review is available only after processing completes.")
    if not services.storage.exists(document_id, "exports/bilingual-document.json"):
        raise DocumentNotFoundError("Bilingual translation result is not available.")

    bilingual = await services.storage.read_json(
        document_id, "exports/bilingual-document.json"
    )
    computed_sha256 = bilingual_result_sha256(bilingual)
    if document.translation_result_sha256:
        result_sha256 = document.translation_result_sha256
    else:
        result_sha256 = computed_sha256
        await services.repository.update_document(
            document_id, translation_result_sha256=result_sha256
        )
        document.translation_result_sha256 = result_sha256
    validate_translation_approval(bilingual, review)
    reviewed_payload = apply_translation_corrections(bilingual, review.corrections)
    await services.storage.write_json(document_id, REVIEWED_BILINGUAL_PATH, reviewed_payload)

    now = datetime.now(UTC)
    persisted = await services.repository.create_translation_review(
        TranslationReview(
            document_id=document_id,
            decision=review.decision,
            reviewer_subject=f"{principal.subject}:{principal.token_fingerprint}",
            note=review.note,
            corrections=[item.model_dump(mode="json") for item in review.corrections],
            processing_version=document.processing_version,
            result_schema_version=TRANSLATION_REVIEW_SCHEMA_VERSION,
            result_sha256=result_sha256,
            created_at=now,
        )
    )
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action=f"translation.review.{review.decision}",
        resource_type="document",
        resource_id=document_id,
    )
    return TranslationReviewRecord.model_validate(persisted).model_copy(
        update={"active_result": True}
    )


@router.post("/{document_id}/assign")
async def assign_document_reviewer(
    request: Request,
    document_id: str,
    reviewer_subject: Annotated[str, Query(min_length=1, max_length=255)],
) -> DocumentDetail:
    services = container(request)
    document = await services.repository.get(document_id)
    principal = _principal(request)
    _enforce_document_access(principal, document, action="assign")
    updated = await services.repository.assign_reviewer(
        document_id, reviewer_subject=reviewer_subject
    )
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action="document.assign",
        resource_type="document",
        resource_id=document_id,
        detail=f"assigned:{reviewer_subject}",
    )
    return DocumentDetail.model_validate(updated)


@router.get("/{document_id}/pages/{page_number}")
async def get_page(
    request: Request,
    document_id: str,
    page_number: int,
) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    if getattr(document, "error_code", None) == "reprocess_cleanup_failed":
        raise DocumentNotFoundError("Page is not available.")
    if document.status == DocumentStatus.QUEUED.value and not document.pages_ready:
        raise DocumentNotFoundError("Page is still being extracted.")
    if document.page_count is None or page_number < 1 or page_number > document.page_count:
        raise DocumentNotFoundError("Page was not found.")
    relative = f"pages/page-{page_number:04d}.json"
    if not services.storage.exists(document_id, relative):
        raise DocumentNotFoundError("Page is still being extracted.")
    payload = await services.storage.read_json(document_id, relative)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    etag = f'"{hashlib.sha256(encoded).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=NO_STORE)
    return JSONResponse(payload, headers={**NO_STORE, "ETag": etag})


@router.get("/{document_id}/downloads/{artifact}")
async def download_artifact(
    request: Request,
    document_id: str,
    artifact: str,
    page: int | None = Query(default=None, ge=1),
) -> FileResponse:
    services = container(request)
    document = await services.repository.get(document_id)
    _enforce_document_access(_principal(request), document)
    if DocumentStatus(document.status) not in {
        DocumentStatus.COMPLETED,
        DocumentStatus.NEEDS_REVIEW,
    }:
        raise ConflictError("Downloads are available only after processing completes.")
    if getattr(document, "error_code", None) == "reprocess_cleanup_failed":
        raise DocumentNotFoundError("Download artifact was not found.")
    if not services.storage.exists(document_id, "manifest.json"):
        raise DocumentNotFoundError("Download artifact was not found.")
    if artifact == "page":
        if page is None:
            raise ConflictError("The page query parameter is required for page JSON.")
        relative = f"pages/page-{page:04d}.json"
        filename = f"{Path(document.original_filename).stem}-page-{page:04d}.json"
    elif artifact == "extracted":
        relative = "exports/extracted-document.json"
        filename = f"{Path(document.original_filename).stem}-extracted.json"
    elif artifact in {"bilingual", "translated"}:
        relative = "exports/bilingual-document.json"
        filename = f"{Path(document.original_filename).stem}-bilingual-machine.json"
    elif artifact == "reviewed-bilingual":
        if document.document_review_status != "approved":
            raise ConflictError(
                "Reviewed bilingual export is available only after translation approval."
            )
        relative = REVIEWED_BILINGUAL_PATH
        filename = f"{Path(document.original_filename).stem}-bilingual-approved.json"
    elif artifact == "manifest":
        relative = "manifest.json"
        filename = f"{Path(document.original_filename).stem}-manifest.json"
    elif artifact == "financial":
        relative = "exports/financial-document.json"
        filename = f"{Path(document.original_filename).stem}-financial.json"
    elif artifact == "financial-csv":
        relative = "exports/financial-document.csv"
        filename = f"{Path(document.original_filename).stem}-financial.csv"
    elif artifact == "financial-xlsx":
        relative = "exports/financial-document.xlsx"
        filename = f"{Path(document.original_filename).stem}-financial.xlsx"
    elif artifact == "financial-validation":
        relative = "validation/financial.json"
        filename = f"{Path(document.original_filename).stem}-financial-validation.json"
    else:
        raise DocumentNotFoundError("Download artifact was not found.")
    if artifact in {"manifest", "reviewed-bilingual"}:
        target = services.storage.artifact_path(document_id, relative)
        if not target.exists():
            raise DocumentNotFoundError("Download artifact was not found.")
        return FileResponse(
            target,
            media_type="application/json",
            filename=filename,
            headers=NO_STORE,
        )
    manifest = await services.storage.read_json(document_id, "manifest.json")
    declared_artifacts = {
        item for item in manifest.get("artifacts", []) if isinstance(item, str)
    }
    if artifact != "page" and relative not in declared_artifacts:
        raise DocumentNotFoundError("Download artifact was not found.")
    target = services.storage.artifact_path(document_id, relative)
    if not target.exists():
        raise DocumentNotFoundError("Download artifact was not found.")
    media_type = {
        ".csv": "text/csv; charset=utf-8",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(target.suffix.lower(), "application/json")
    return FileResponse(
        target,
        media_type=media_type,
        filename=filename,
        headers=NO_STORE,
    )


@router.post("/{document_id}/cancel", response_model=CancelDocumentResponse, status_code=200)
async def cancel_document(request: Request, document_id: str) -> CancelDocumentResponse:
    services = container(request)
    document = await services.repository.get(document_id)
    principal = _principal(request)
    _enforce_document_access(principal, document)
    document = await services.document_service.cancel(document_id)
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action="document.cancel",
        resource_type="document",
        resource_id=document_id,
    )
    return CancelDocumentResponse(
        document_id=document.id,
        status=document.status,
        message="Processing was cancelled.",
    )


@router.post("/{document_id}/retry", response_model=DocumentCreateResponse, status_code=202)
async def retry_document(
    request: Request,
    document_id: str,
    mode: str = Query(default="resume"),
) -> DocumentCreateResponse:
    services = container(request)
    try:
        retry_mode = RetryMode(mode)
    except ValueError as exc:
        raise InvalidDocumentError(
            "Retry mode must be resume, retranslate, or reprocess."
        ) from exc
    document = await services.repository.get(document_id)
    principal = _principal(request)
    _enforce_document_access(principal, document)
    await services.document_service.retry(document_id, mode=retry_mode)
    await services.runner.enqueue(document_id)
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action=f"document.retry.{retry_mode.value}",
        resource_type="document",
        resource_id=document_id,
    )
    return DocumentCreateResponse(
        document_id=document_id,
        status=DocumentStatus.QUEUED.value,
        status_url=f"{services.settings.api_v1_prefix}/documents/{document_id}",
        processing_profile=document.processing_profile,
        data_class=document.data_class,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    principal = _principal(request)
    _enforce_document_access(principal, document, action="delete")
    await services.document_service.delete(document_id)
    await AuditService(services.repository).record(
        organization_id=principal.organization_id,
        actor_subject=principal.subject,
        action="document.delete",
        resource_type="document",
        resource_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
