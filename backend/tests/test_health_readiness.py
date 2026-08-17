"""Regression: /health/ready's response contract must include `limits`.

An earlier revision trimmed /health/ready down to {status, database, storage,
worker}, dropping `limits` (max_upload_size_mb, max_document_pages,
job_poll_timeout_minutes) along with the more sensitive `azure_configured`/
`auth_required`/policy-default fields. The frontend still reads
`health.limits.max_upload_size_mb` and `health.limits.job_poll_timeout_minutes`
for real client-side behavior (upload request timeout scaling, poll duration),
not just display - so its absence silently fell back to hardcoded defaults
instead of the server's actual configured limits. `limits` is non-sensitive
(already published in .env.example) and was restored; the more sensitive
configuration fields correctly stay behind auth on /health/dependencies.

Confirmed by a second independent code review on 2026-08-12.
"""

import json
from pathlib import Path
from typing import Any

from starlette.requests import Request

from app.api.routes.health import readiness
from app.core.config import Settings
from app.database.session import Database


class _FakeRunner:
    tasks = {"worker-1": object()}


async def _container(tmp_path: Path) -> Any:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'health.db'}")
    await database.create_schema()
    settings = Settings(
        auth_required=False,
        storage_root=tmp_path / "storage",
        max_upload_size_mb=150,
        max_document_pages=300,
    )

    class _Container:
        pass

    container = _Container()
    container.settings = settings  # type: ignore[attr-defined]
    container.database = database  # type: ignore[attr-defined]
    container.runner = _FakeRunner()  # type: ignore[attr-defined]
    return container


def _request(container: object) -> Request:
    from types import SimpleNamespace

    app = SimpleNamespace(state=SimpleNamespace(container=container))
    return Request({"type": "http", "app": app, "headers": []})


async def test_readiness_response_includes_operating_limits(tmp_path: Path) -> None:
    container = await _container(tmp_path)

    response = await readiness(_request(container))

    assert response.status_code == 200
    payload = json.loads(bytes(response.body).decode("utf-8"))
    assert payload["status"] == "ready"
    assert payload["limits"]["max_upload_size_mb"] == 150
    assert payload["limits"]["max_document_pages"] == 300
    assert "job_poll_timeout_minutes" in payload["limits"]
    # Configuration/policy detail must NOT be on this unauthenticated endpoint.
    assert "azure_configured" not in payload
    assert "auth_required" not in payload
