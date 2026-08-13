"""Unit tests for local PRD-shaped authorization helpers."""

import pytest

from app.core.authorization import (
    ROLE_AUDITOR,
    ROLE_CASEWORKER,
    ROLE_ORG_ADMIN,
    ROLE_REVIEWER,
    AuthPrincipal,
    can_access_document,
    require_document_access,
)
from app.core.exceptions import AuthorizationError


def _principal(*, subject: str, roles: set[str], org: str = "org-local") -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        token_fingerprint="tok-test",
        organization_id=org,
        roles=frozenset(roles),
    )


def test_owner_and_admin_can_access_document() -> None:
    owner = _principal(subject="cw-1", roles={ROLE_CASEWORKER})
    admin = _principal(subject="admin", roles={ROLE_ORG_ADMIN})
    assert can_access_document(
        owner,
        organization_id="org-local",
        owner_subject="cw-1",
        assigned_reviewer_subject=None,
        document_review_status="draft",
    )
    assert can_access_document(
        admin,
        organization_id="org-local",
        owner_subject="cw-1",
        assigned_reviewer_subject=None,
        document_review_status="approved",
    )


def test_cross_org_access_is_denied() -> None:
    principal = _principal(subject="cw-1", roles={ROLE_ORG_ADMIN}, org="org-a")
    assert not can_access_document(
        principal,
        organization_id="org-b",
        owner_subject="cw-1",
        assigned_reviewer_subject=None,
        document_review_status="draft",
    )


def test_reviewer_can_open_needs_review_documents() -> None:
    reviewer = _principal(subject="rev-1", roles={ROLE_REVIEWER})
    assert can_access_document(
        reviewer,
        organization_id="org-local",
        owner_subject="someone-else",
        assigned_reviewer_subject=None,
        document_review_status="needs_review",
    )


def test_auditor_cannot_review() -> None:
    auditor = _principal(subject="audit-1", roles={ROLE_AUDITOR})
    with pytest.raises(AuthorizationError, match="not allowed to review"):
        require_document_access(
            auditor,
            organization_id="org-local",
            owner_subject="cw-1",
            action="review",
        )


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_auditor_cannot_retry_or_cancel(action: str) -> None:
    # Auditors have org-wide read, but retry/cancel mutate processing state
    # and must stay owner-scoped. AuthorizationError maps to HTTP 403.
    auditor = _principal(subject="audit-1", roles={ROLE_AUDITOR})
    with pytest.raises(AuthorizationError, match="retry or cancel") as excinfo:
        require_document_access(
            auditor,
            organization_id="org-local",
            owner_subject="cw-1",
            action=action,
        )
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_owner_can_retry_and_cancel(action: str) -> None:
    owner = _principal(subject="cw-1", roles={ROLE_CASEWORKER})
    require_document_access(
        owner,
        organization_id="org-local",
        owner_subject="cw-1",
        action=action,
    )


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_non_owner_reviewer_cannot_retry_or_cancel(action: str) -> None:
    reviewer = _principal(subject="rev-1", roles={ROLE_REVIEWER})
    with pytest.raises(AuthorizationError, match="retry or cancel"):
        require_document_access(
            reviewer,
            organization_id="org-local",
            owner_subject="cw-1",
            document_review_status="needs_review",
            action=action,
        )


def test_delete_requires_owner_or_admin() -> None:
    auditor = _principal(subject="audit-1", roles={ROLE_AUDITOR})
    with pytest.raises(AuthorizationError, match="not allowed to delete"):
        require_document_access(
            auditor,
            organization_id="org-local",
            owner_subject="cw-1",
            action="delete",
        )
    caseworker = _principal(subject="cw-2", roles={ROLE_CASEWORKER})
    require_document_access(
        caseworker,
        organization_id="org-local",
        owner_subject="cw-2",
        action="delete",
    )
