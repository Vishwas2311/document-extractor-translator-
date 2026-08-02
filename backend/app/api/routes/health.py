from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.auth import AuthPrincipal, optional_principal, require_principal

router = APIRouter()


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
        root: Path = settings.storage_root
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".ready_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
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
    _: AuthPrincipal = Depends(require_principal),
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
        },
    }


@router.get("/health/session")
async def session_status(
    request: Request,
    principal: AuthPrincipal | None = Depends(optional_principal),
) -> dict[str, object]:
    settings = request.app.state.container.settings
    return {
        "authenticated": principal is not None
        and (not settings.auth_required or principal.subject != "anonymous-dev"),
        "auth_required": settings.auth_required,
        "subject": principal.subject if principal else None,
        "security_label": (
            "Authenticated local API token"
            if principal and settings.auth_required
            else "Unauthenticated development mode"
        ),
        "data_policy": "Synthetic or approved de-identified data only",
    }
