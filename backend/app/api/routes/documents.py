import hashlib
import json
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.auth import AuthPrincipal, require_principal
from app.core.enums import TERMINAL_DOCUMENT_STATUSES, DocumentStatus, RetryMode
from app.core.exceptions import ConflictError, DocumentNotFoundError, InvalidDocumentError
from app.dependencies.services import ServiceContainer
from app.schemas.document import (
    CancelDocumentResponse,
    DocumentCreateResponse,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    PageSummary,
)
from app.schemas.page import PageResult

router = APIRouter(dependencies=[Depends(require_principal)])

NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, private", "Pragma": "no-cache"}


def container(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.container)


@router.post("", response_model=DocumentCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    data_class: Annotated[str | None, Form()] = None,
    processing_profile: Annotated[str | None, Form()] = None,
    _: AuthPrincipal = Depends(require_principal),
) -> DocumentCreateResponse:
    services = container(request)
    document = await services.document_service.create_upload(
        file,
        data_class=data_class,
        processing_profile=processing_profile,
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
    items, total = await container(request).repository.list(page, page_size)
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
    source = services.storage.source_path(document_id, document.stored_extension)
    return FileResponse(
        source,
        media_type=document.content_type,
        filename=document.original_filename,
        content_disposition_type="inline",
        headers=NO_STORE,
    )


@router.get("/{document_id}/pages", response_model=list[PageSummary])
async def list_pages(request: Request, document_id: str) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
    if document.page_count is None:
        return JSONResponse([], headers=NO_STORE)

    index_path = "pages/index.json"
    if services.storage.exists(document_id, index_path):
        index = await services.storage.read_json(document_id, index_path)
        summaries = [
            PageSummary.model_validate(item).model_dump(mode="json")
            for item in index.get("pages", [])
            if isinstance(item, dict)
            and 1 <= int(item.get("page_number", 0)) <= int(document.page_count)
        ]
        return JSONResponse(summaries, headers=NO_STORE)

    summaries: list[PageSummary] = []
    for number in range(1, document.page_count + 1):
        relative = f"pages/page-{number:04d}.json"
        if not services.storage.exists(document_id, relative):
            continue
        payload = PageResult.model_validate(await services.storage.read_json(document_id, relative))
        summaries.append(
            PageSummary(
                page_number=number,
                width=payload.page.width,
                height=payload.page.height,
                unit=payload.page.unit,
                angle=payload.page.angle,
                block_count=len(payload.blocks),
                table_count=len(payload.tables),
                review_required=bool(payload.warnings)
                or any(block.review_required for block in payload.blocks)
                or any(
                    cell.review_required for table in payload.tables for cell in table.cells
                ),
            )
        )
    return JSONResponse(
        [item.model_dump(mode="json") for item in summaries],
        headers=NO_STORE,
    )


@router.get("/{document_id}/pages/{page_number}")
async def get_page(
    request: Request,
    document_id: str,
    page_number: int,
) -> Response:
    services = container(request)
    document = await services.repository.get(document_id)
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
        filename = f"{Path(document.original_filename).stem}-bilingual.json"
    else:
        raise DocumentNotFoundError("Download artifact was not found.")
    target = services.storage.artifact_path(document_id, relative)
    if not target.exists():
        raise DocumentNotFoundError("Download artifact was not found.")
    return FileResponse(
        target,
        media_type="application/json",
        filename=filename,
        headers=NO_STORE,
    )


@router.post("/{document_id}/cancel", response_model=CancelDocumentResponse, status_code=200)
async def cancel_document(request: Request, document_id: str) -> CancelDocumentResponse:
    services = container(request)
    document = await services.document_service.cancel(document_id)
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
    await services.document_service.retry(document_id, mode=retry_mode)
    await services.runner.enqueue(document_id)
    return DocumentCreateResponse(
        document_id=document_id,
        status=DocumentStatus.QUEUED.value,
        status_url=f"{services.settings.api_v1_prefix}/documents/{document_id}",
        processing_profile=document.processing_profile,
        data_class=document.data_class,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(request: Request, document_id: str) -> Response:
    await container(request).document_service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
