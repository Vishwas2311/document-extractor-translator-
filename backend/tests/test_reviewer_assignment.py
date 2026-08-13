"""Reviewer-assignment validation: same organization, known principal, review role."""

import json

import pytest

from app.core.auth import validate_reviewer_assignment
from app.core.config import Settings
from app.core.exceptions import AuthorizationError


def _settings_with_directory(**overrides: object) -> Settings:
    principals = {
        "token-reviewer": {
            "subject": "reviewer-1",
            "organization_id": "org-a",
            "roles": ["reviewer"],
        },
        "token-caseworker": {
            "subject": "caseworker-1",
            "organization_id": "org-a",
            "roles": ["caseworker"],
        },
        "token-otherorg": {
            "subject": "reviewer-2",
            "organization_id": "org-b",
            "roles": ["reviewer"],
        },
    }
    values: dict[str, object] = {
        "auth_required": True,
        "api_auth_principals": json.dumps(principals),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_valid_same_org_reviewer_is_accepted() -> None:
    settings = _settings_with_directory()
    validate_reviewer_assignment(
        settings, reviewer_subject="reviewer-1", organization_id="org-a"
    )


def test_unknown_subject_is_rejected() -> None:
    settings = _settings_with_directory()
    with pytest.raises(AuthorizationError):
        validate_reviewer_assignment(
            settings, reviewer_subject="ghost", organization_id="org-a"
        )


def test_cross_organization_assignment_is_rejected() -> None:
    settings = _settings_with_directory()
    with pytest.raises(AuthorizationError):
        validate_reviewer_assignment(
            settings, reviewer_subject="reviewer-2", organization_id="org-a"
        )


def test_non_review_role_is_rejected() -> None:
    settings = _settings_with_directory()
    with pytest.raises(AuthorizationError):
        validate_reviewer_assignment(
            settings, reviewer_subject="caseworker-1", organization_id="org-a"
        )


def test_empty_subject_is_rejected() -> None:
    settings = _settings_with_directory()
    with pytest.raises(AuthorizationError):
        validate_reviewer_assignment(
            settings, reviewer_subject="   ", organization_id="org-a"
        )


def test_no_directory_in_development_is_allowed() -> None:
    settings = Settings(auth_required=False)
    validate_reviewer_assignment(
        settings, reviewer_subject="anyone", organization_id="org-local"
    )


def test_no_directory_with_entra_fails_closed() -> None:
    settings = Settings(
        auth_required=True,
        auth_mode="entra_jwt",
        entra_tenant_id="tid",
        entra_client_id="cid",
        entra_issuer="https://issuer",
        entra_jwks_url="https://issuer/keys",
    )
    with pytest.raises(AuthorizationError):
        validate_reviewer_assignment(
            settings, reviewer_subject="reviewer-1", organization_id="org-a"
        )
