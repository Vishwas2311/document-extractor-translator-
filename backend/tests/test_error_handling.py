"""Locks in the normalized error envelope for every exception handler registered on
the FastAPI app in `app.main` - previously verified only by manual curl requests
against a running dev server, not by a committed, regression-proof test."""

import json
from types import SimpleNamespace

from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core.exceptions import DocumentNotFoundError
from app.main import (
    app,
    app_error_handler,
    http_exception_handler,
    integrity_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)


def _request(request_id: str = "req-test-123") -> Request:
    """Mirrors `test_document_routes.py`'s `_request()` helper: a minimal ASGI scope is
    enough for Starlette's `Request.url`/`.state` to work without a real transport."""
    scope_app = SimpleNamespace(state=SimpleNamespace(container=None))
    scope = {"type": "http", "app": scope_app, "path": "/api/v1/documents", "headers": []}
    request = Request(scope)
    request.state.request_id = request_id
    return request


def _body(response: Response) -> dict[str, object]:
    return dict(json.loads(bytes(response.body)))


def _text(response: Response) -> str:
    return bytes(response.body).decode()


async def test_app_error_handler_normalizes_shape_and_allowlists_details() -> None:
    exc = DocumentNotFoundError("Document was not found.")
    response = await app_error_handler(_request(), exc)

    assert response.status_code == 404
    body = _body(response)
    assert body == {
        "code": "document_not_found",
        "message": "Document was not found.",
        "request_id": "req-test-123",
        "retryable": False,
        "details": {},
    }


async def test_validation_error_handler_never_leaks_pydantic_internals() -> None:
    exc = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "file"),
                "msg": "Field required",
                "input": None,
            }
        ]
    )
    response = await validation_error_handler(_request(), exc)

    assert response.status_code == 422
    body = _body(response)
    assert body["code"] == "validation_error"
    assert body["message"] == "The request was invalid. Please check your input and try again."
    assert body["request_id"] == "req-test-123"
    assert body["retryable"] is False
    # The raw pydantic error internals (field path, input value) must never appear.
    raw_body = _text(response)
    assert "loc" not in raw_body
    assert "Field required" not in raw_body


async def test_http_exception_handler_maps_every_status_to_a_safe_message() -> None:
    expected = {
        401: "Authentication is required to access this resource.",
        403: "You don't have permission to perform this action.",
        404: "The requested resource was not found.",
        405: "This action is not supported.",
        409: "This action conflicts with the current state of the resource.",
        413: "The uploaded file exceeds the allowed size.",
        415: "The uploaded file type is not supported.",
        429: "Too many requests. Please slow down and try again shortly.",
    }
    for status_code, message in expected.items():
        exc = StarletteHTTPException(status_code=status_code, detail="raw internal detail text")
        response = await http_exception_handler(_request(), exc)
        assert response.status_code == status_code
        body = _body(response)
        assert body["code"] == "http_error"
        assert body["message"] == message
        # The framework's raw `detail` string must never leak into the response.
        assert "raw internal detail text" not in _text(response)


async def test_http_exception_handler_falls_back_for_an_unmapped_status() -> None:
    response = await http_exception_handler(_request(), StarletteHTTPException(status_code=451))
    assert response.status_code == 451
    assert _body(response)["message"] == "The request could not be completed."


async def test_http_exception_handler_preserves_exception_headers() -> None:
    # Starlette's router raises exactly this shape for a method-not-allowed match -
    # the Allow header must survive so callers know which methods are permitted.
    exc = StarletteHTTPException(status_code=405, headers={"Allow": "GET, POST"})
    response = await http_exception_handler(_request(), exc)

    assert response.status_code == 405
    assert response.headers["allow"] == "GET, POST"
    assert response.headers["cache-control"] == "no-store"


async def test_integrity_error_handler_maps_a_constraint_violation_to_409() -> None:
    exc = IntegrityError(
        "INSERT INTO documents (...) VALUES (...)",
        {},
        Exception("UNIQUE constraint failed: documents.id"),
    )
    response = await integrity_error_handler(_request(), exc)

    assert response.status_code == 409
    body = _body(response)
    assert body["code"] == "conflict"
    assert body["message"] == "This action conflicts with the current state of the resource."
    # The raw SQL/constraint text must never leak into the response.
    raw_body = _text(response)
    assert "UNIQUE constraint" not in raw_body
    assert "INSERT INTO" not in raw_body


async def test_unexpected_error_handler_never_leaks_exception_text() -> None:
    exc = ValueError("connection refused to internal-host:5432 with password=hunter2")
    response = await unexpected_error_handler(_request(), exc)

    assert response.status_code == 500
    body = _body(response)
    assert body == {
        "code": "internal_error",
        "message": "The request could not be completed.",
        "request_id": "req-test-123",
        "retryable": False,
        "details": {},
    }
    raw_body = _text(response)
    assert "hunter2" not in raw_body
    assert "internal-host" not in raw_body


async def test_all_handlers_set_no_store_cache_control() -> None:
    responses = [
        await app_error_handler(_request(), DocumentNotFoundError("x")),
        await validation_error_handler(_request(), RequestValidationError([])),
        await http_exception_handler(_request(), StarletteHTTPException(status_code=404)),
        await integrity_error_handler(_request(), IntegrityError("x", {}, Exception("x"))),
        await unexpected_error_handler(_request(), Exception("x")),
    ]
    for response in responses:
        assert response.headers["cache-control"] == "no-store"


def test_handlers_are_registered_on_the_app_for_their_exact_exception_types() -> None:
    # Confirms the decorators in main.py actually wired these functions up - a handler
    # that's merely defined but never registered would pass every test above while
    # doing nothing at runtime.
    registered = {exc_type: handler for exc_type, handler in app.exception_handlers.items()}
    assert registered[RequestValidationError] is validation_error_handler
    assert registered[StarletteHTTPException] is http_exception_handler
    assert registered[IntegrityError] is integrity_error_handler
    assert registered[Exception] is unexpected_error_handler
