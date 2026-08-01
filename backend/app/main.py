from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.dependencies.services import create_container
from app.middleware.request_context import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level, settings.log_format == "json")
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.container = await create_container(settings)
    await logger.ainfo("application_started", environment=settings.app_env)
    try:
        yield
    finally:
        await app.state.container.close()
        await logger.ainfo("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Mandarin and Arabic document extraction and English translation POC.",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "If-None-Match"],
    expose_headers=["ETag", "X-Request-ID"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", "unknown"),
            "retryable": getattr(exc, "retryable", False),
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    await logger.aexception(
        "unhandled_request_error",
        request_id=getattr(request.state, "request_id", "unknown"),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "The request could not be completed.",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "retryable": False,
            "details": {},
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "api": settings.api_v1_prefix,
        "docs": "/docs",
    }
