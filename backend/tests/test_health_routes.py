from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from app.api.routes.health import azure_openai_live_check
from app.core.auth import AuthPrincipal


class _FakeTranslator:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    async def check_connectivity(self) -> dict[str, Any]:
        return self._result


def _request(container: object) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    return Request({"type": "http", "app": app, "headers": []})


def _principal() -> AuthPrincipal:
    return AuthPrincipal(subject="synthetic-reviewer", token_fingerprint="tok-hash-only")


@pytest.mark.asyncio
async def test_azure_openai_live_check_reports_success() -> None:
    container = SimpleNamespace(
        translator=_FakeTranslator(
            {"reachable": True, "http_status": 200, "error_category": None, "detail": None}
        )
    )

    response = await azure_openai_live_check(_request(container), _principal())

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_azure_openai_live_check_reports_failure_with_503() -> None:
    # 503, not the provider's own status code, mirrors /health/ready's convention:
    # this endpoint's status reflects "is Azure OpenAI reachable", not a passthrough
    # of whatever Azure returned (that detail is in the body's http_status field).
    container = SimpleNamespace(
        translator=_FakeTranslator(
            {
                "reachable": False,
                "http_status": 401,
                "error_category": "auth",
                "detail": "Azure rejected the request's credentials or permissions.",
            }
        )
    )

    response = await azure_openai_live_check(_request(container), _principal())

    assert response.status_code == 503
