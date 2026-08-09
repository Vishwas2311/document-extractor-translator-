from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.dependencies.services import create_container
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level, settings.log_format == "json")
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.container = await create_container(settings)
    await logger.ainfo(
        "application_started",
        environment=settings.app_env,
        auth_required=settings.auth_required,
        default_profile=settings.default_processing_profile,
    )
    try:
        yield
    finally:
        await app.state.container.close()
        await logger.ainfo("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description=(
        "Multilingual document extraction and detected non-English to English translation. "
        "Local production-oriented evaluation build: authenticated API, processing profiles, "
        "synthetic/de-identified data only unless an approved exception is configured."
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(RateLimitMiddleware, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "If-None-Match", "Authorization"],
    expose_headers=["ETag", "X-Request-ID", "Cache-Control"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    # Only expose allowlisted detail keys to clients.
    public_details = {
        key: value
        for key, value in exc.details.items()
        if key in {"profile", "requested", "allowed", "data_class", "reason", "service"}
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", "unknown"),
            "retryable": getattr(exc, "retryable", False),
            "details": public_details,
        },
        headers={"Cache-Control": "no-store"},
    )


_SAFE_STATUS_MESSAGES = {
    400: "The request could not be understood. Please check your input and try again.",
    401: "Authentication is required to access this resource.",
    403: "You don't have permission to perform this action.",
    404: "The requested resource was not found.",
    405: "This action is not supported.",
    409: "This action conflicts with the current state of the resource.",
    413: "The uploaded file exceeds the allowed size.",
    415: "The uploaded file type is not supported.",
    422: "The request was invalid. Please check your input and try again.",
    429: "Too many requests. Please slow down and try again shortly.",
}


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await logger.awarning(
        "request_validation_failed",
        request_id=request_id,
        path=request.url.path,
        error_count=len(exc.errors()),
    )
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": _SAFE_STATUS_MESSAGES[422],
            "request_id": request_id,
            "retryable": False,
            "details": {},
        },
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    if exc.status_code >= 500:
        await logger.aexception(
            "unhandled_http_exception",
            request_id=request_id,
            path=request.url.path,
            status_code=exc.status_code,
        )
    else:
        await logger.awarning(
            "http_exception",
            request_id=request_id,
            path=request.url.path,
            status_code=exc.status_code,
        )
    message = _SAFE_STATUS_MESSAGES.get(
        exc.status_code, "The request could not be completed."
    )
    # Starlette's router raises HTTPException(405, headers={"Allow": "..."}) on a
    # method-not-allowed match, per RFC 7231 - preserve any headers the exception
    # carried (our own no-store directive still wins if it collides).
    headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "http_error",
            "message": message,
            "request_id": request_id,
            "retryable": False,
            "details": {},
        },
        headers=headers,
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await logger.awarning(
        "database_integrity_error",
        request_id=request_id,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=409,
        content={
            "code": "conflict",
            "message": _SAFE_STATUS_MESSAGES[409],
            "request_id": request_id,
            "retryable": False,
            "details": {},
        },
        headers={"Cache-Control": "no-store"},
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
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, object]:
    return {
        "name": settings.app_name,
        "api": settings.api_v1_prefix,
        "auth_required": settings.auth_required,
        "docs": "/docs" if settings.docs_enabled else None,
        "data_policy": "synthetic_or_approved_deidentified_only",
    }
