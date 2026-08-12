from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.middleware.security_headers import (
    _API_CSP,
    _DOCS_CSP,
    SecurityHeadersMiddleware,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/v1/thing")
    async def thing() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/docs")
    async def docs() -> dict[str, str]:
        return {"docs": "ui"}

    return app


def test_api_response_carries_locked_down_headers() -> None:
    client = TestClient(_app())
    response = client.get("/api/v1/thing")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    assert response.headers["Content-Security-Policy"] == _API_CSP


def test_docs_route_uses_relaxed_csp() -> None:
    client = TestClient(_app())
    response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == _DOCS_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_middleware_does_not_override_existing_header() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/custom")
    async def custom() -> JSONResponse:
        return JSONResponse({"ok": "yes"}, headers={"X-Frame-Options": "SAMEORIGIN"})

    client = TestClient(app)
    response = client.get("/custom")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
