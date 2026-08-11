import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.auth import AuthPrincipal, optional_principal, require_principal

router = APIRouter()


def _probe_storage(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".ready_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


@router.get("/health")
@router.get("/health/live")
async def liveness() -> dict[str, object]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    container = request.app.state.container
    settings = container.settings
    database_status = "ready"
    storage_status = "ready"
    worker_status = "ready"
    overall = "ready"

    try:
        async with container.database.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
        overall = "not_ready"

    try:
        await asyncio.to_thread(_probe_storage, settings.storage_root)
    except Exception:
        storage_status = "unavailable"
        overall = "not_ready"

    if not getattr(container.runner, "tasks", None):
        worker_status = "unavailable"
        overall = "not_ready"

    payload = {
        "status": overall,
        "database": database_status,
        "storage": storage_status,
        "worker": worker_status,
        "auth_required": settings.auth_required,
        "default_processing_profile": settings.default_processing_profile,
        "default_data_class": settings.default_data_class,
        "limits": {
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_document_pages": settings.max_document_pages,
            "di_page_range_size": settings.di_page_range_size,
            "di_range_concurrency": settings.di_range_concurrency,
            "translation_concurrency": settings.translation_concurrency,
            "job_poll_timeout_minutes": 90,
        },
        "azure_configured": {
            "document_intelligence": settings.document_intelligence_configured,
            "openai": settings.azure_openai_configured,
        },
        "openai_deployment_configured": bool(settings.azure_openai_deployment),
    }
    status_code = 200 if overall == "ready" else 503
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/health/dependencies")
async def dependency_configuration(
    request: Request,
    _: Annotated[AuthPrincipal, Depends(require_principal)],
) -> dict[str, object]:
    settings = request.app.state.container.settings
    return {
        "document_intelligence": {
            "configured": settings.document_intelligence_configured,
            "model": settings.azure_document_intelligence_model_id,
            "auth_mode": settings.azure_auth_mode,
        },
        "azure_openai": {
            "configured": settings.azure_openai_configured,
            "deployment": settings.azure_openai_deployment,
            "api": "v1",
            "auth_mode": settings.azure_auth_mode,
        },
        "processing": {
            "default_profile": settings.default_processing_profile,
            "default_data_class": settings.default_data_class,
            "allow_synthetic_raw_llm": settings.allow_synthetic_raw_llm,
            "genai_raw_exception_enabled": settings.genai_raw_exception_enabled,
            "financial_extraction_mode": settings.financial_extraction_mode,
            "financial_classifier_configured": bool(
                settings.financial_classifier_model_id
            ),
            "financial_classifier_version": settings.financial_classifier_version,
        },
    }


@router.get("/health/dependencies/azure-openai/live")
async def azure_openai_live_check(
    request: Request,
    _: Annotated[AuthPrincipal, Depends(require_principal)],
) -> JSONResponse:
    """Make one real, minimal call to Azure OpenAI and report back whether it
    succeeded and why not if it didn't - unlike /health/dependencies (which only
    reports whether credentials are *present*), this actually exercises the
    network path, auth, and configured deployment. Never returns document
    content or the raw provider error, only a safe status/category."""
    translator = request.app.state.container.translator
    result = await translator.check_connectivity()
    status_code = 200 if result["reachable"] else 503
    return JSONResponse(result, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/health/session")
async def session_status(
    request: Request,
    principal: Annotated[AuthPrincipal | None, Depends(optional_principal)],
) -> dict[str, object]:
    settings = request.app.state.container.settings
    return {
        "authenticated": principal is not None
        and (not settings.auth_required or principal.subject != "anonymous-dev"),
        "auth_required": settings.auth_required,
        "subject": principal.subject if principal else None,
        "organization_id": principal.organization_id if principal else None,
        "roles": sorted(principal.roles) if principal else [],
        "security_label": (
            "Authenticated local API token"
            if principal and settings.auth_required
            else "Unauthenticated development mode"
        ),
        "data_policy": "Synthetic or approved de-identified data only",
    }
