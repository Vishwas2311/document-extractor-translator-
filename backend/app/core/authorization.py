"""Local identity and role-based access helpers for PRD-shaped authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.exceptions import AuthorizationError


ROLE_CASEWORKER = "caseworker"
ROLE_REVIEWER = "reviewer"
ROLE_ORG_ADMIN = "org_admin"
ROLE_AUDITOR = "auditor"
ROLE_OPERATOR = "operator"

ALL_ROLES = frozenset(
    {
        ROLE_CASEWORKER,
        ROLE_REVIEWER,
        ROLE_ORG_ADMIN,
        ROLE_AUDITOR,
        ROLE_OPERATOR,
    }
)


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    token_fingerprint: str
    organization_id: str = "org-local"
    roles: frozenset[str] = frozenset({ROLE_ORG_ADMIN})

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def normalize_roles(roles: Iterable[str] | None) -> frozenset[str]:
    if not roles:
        return frozenset({ROLE_ORG_ADMIN})
    cleaned = {str(role).strip().casefold() for role in roles if str(role).strip()}
    unknown = cleaned - ALL_ROLES
    if unknown:
        raise ValueError(f"Unknown auth roles: {', '.join(sorted(unknown))}")
    return frozenset(cleaned)


def can_list_organization(principal: AuthPrincipal) -> bool:
    return principal.has_role(ROLE_ORG_ADMIN, ROLE_AUDITOR, ROLE_OPERATOR)


def can_access_document(
    principal: AuthPrincipal,
    *,
    organization_id: str,
    owner_subject: str,
    assigned_reviewer_subject: str | None,
    document_review_status: str | None,
) -> bool:
    if principal.organization_id != organization_id:
        return False
    if principal.has_role(ROLE_ORG_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR):
        return True
    if principal.subject == owner_subject:
        return True
    if assigned_reviewer_subject and principal.subject == assigned_reviewer_subject:
        return True
    if principal.has_role(ROLE_REVIEWER) and document_review_status in {
        "needs_review",
        "in_review",
        None,
        "draft",
    }:
        # Reviewers may open org documents that still need human attention.
        return True
    return False


def require_document_access(
    principal: AuthPrincipal,
    *,
    organization_id: str,
    owner_subject: str,
    assigned_reviewer_subject: str | None = None,
    document_review_status: str | None = None,
    action: str = "read",
) -> None:
    if can_access_document(
        principal,
        organization_id=organization_id,
        owner_subject=owner_subject,
        assigned_reviewer_subject=assigned_reviewer_subject,
        document_review_status=document_review_status,
    ):
        if action in {"review", "approve"} and not principal.has_role(
            ROLE_REVIEWER, ROLE_ORG_ADMIN, ROLE_CASEWORKER, ROLE_OPERATOR
        ):
            raise AuthorizationError("This principal is not allowed to review documents.")
        if action == "delete" and not (
            principal.subject == owner_subject
            or principal.has_role(ROLE_ORG_ADMIN, ROLE_OPERATOR)
        ):
            raise AuthorizationError("This principal is not allowed to delete the document.")
        if action == "assign" and not principal.has_role(
            ROLE_ORG_ADMIN, ROLE_CASEWORKER, ROLE_OPERATOR
        ):
            raise AuthorizationError("This principal is not allowed to assign reviewers.")
        return
    raise AuthorizationError("You are not authorized to access this document.")
