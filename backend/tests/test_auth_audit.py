"""Content-free auditing of authentication failures and authorization denials."""

from types import SimpleNamespace

from starlette.requests import Request

from app.core.auth import AuthPrincipal
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    InvalidDocumentError,
)
from app.main import _audit_auth_failure
from app.models.audit_event import AuditEvent


class FakeRepo:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def create_audit_event(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return event


def _request(container: object, principal: AuthPrincipal | None = None) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(container=container))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
            "app": app,
        }
    )
    request.state.request_id = "req-1"
    if principal is not None:
        request.state.principal = principal
    return request


async def test_authorization_denial_is_audited_with_principal() -> None:
    repo = FakeRepo()
    principal = AuthPrincipal(
        subject="user-1", token_fingerprint="tok", organization_id="org-a"
    )
    request = _request(SimpleNamespace(repository=repo), principal)

    await _audit_auth_failure(request, AuthorizationError("nope"))

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event.action == "auth.denied"
    assert event.result == "failure"
    assert event.actor_subject == "user-1"
    assert event.organization_id == "org-a"
    assert event.resource_type == "session"
    assert event.correlation_id == "req-1"


async def test_authentication_failure_without_principal_is_unknown_actor() -> None:
    repo = FakeRepo()
    request = _request(SimpleNamespace(repository=repo))

    await _audit_auth_failure(request, AuthenticationError("missing token"))

    assert len(repo.events) == 1
    event = repo.events[0]
    assert event.action == "auth.failed"
    assert event.actor_subject == "unknown"
    assert event.organization_id == "unknown"


async def test_non_auth_error_is_not_audited() -> None:
    repo = FakeRepo()
    request = _request(SimpleNamespace(repository=repo))

    await _audit_auth_failure(request, InvalidDocumentError("bad"))

    assert repo.events == []


async def test_missing_repository_does_not_raise() -> None:
    request = _request(SimpleNamespace(repository=SimpleNamespace()))
    await _audit_auth_failure(request, AuthorizationError("nope"))
