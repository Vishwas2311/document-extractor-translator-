from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
@router.get("/health/live")
async def liveness() -> dict[str, object]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> dict[str, object]:
    container = request.app.state.container
    return {
        "status": "ready",
        "database": "ready",
        "storage": "ready",
        "worker": "ready",
        "azure_configured": {
            "document_intelligence": container.settings.document_intelligence_configured,
            "openai": container.settings.azure_openai_configured,
        },
    }


@router.get("/health/dependencies")
async def dependency_configuration(request: Request) -> dict[str, object]:
    settings = request.app.state.container.settings
    return {
        "document_intelligence": {
            "configured": settings.document_intelligence_configured,
            "model": settings.azure_document_intelligence_model_id,
        },
        "azure_openai": {
            "configured": settings.azure_openai_configured,
            "deployment": settings.azure_openai_deployment,
            "api": "v1",
        },
    }
