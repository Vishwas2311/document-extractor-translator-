"""Bearer-token authentication with local principal registry.

Production Entra/JWT validation replaces this boundary. Until then, every document
route requires ``Authorization: Bearer <token>``. Optional ``API_AUTH_PRINCIPALS``
JSON maps tokens to subject, organization, and roles.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.authorization import (
    ROLE_ORG_ADMIN,
    AuthPrincipal,
    normalize_roles,
)
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.dependencies.services import ServiceContainer

_bearer = HTTPBearer(auto_error=False)


def _settings(request: Request) -> Settings:
    container: ServiceContainer = request.app.state.container
    return container.settings


def _fingerprint(token: str) -> str:
    return "tok-" + hashlib.sha256(token.encode()).hexdigest()[:16]


def _principal_from_registry(token: str, settings: Settings) -> AuthPrincipal | None:
    mapping = settings.auth_principal_map
    entry = mapping.get(token)
    if not isinstance(entry, dict):
        return None
    subject = str(entry.get("subject") or "local-api-token").strip() or "local-api-token"
    organization_id = (
        str(entry.get("organization_id") or entry.get("organizationId") or "org-local").strip()
        or "org-local"
    )
    roles_raw = entry.get("roles")
    roles: list[str]
    if isinstance(roles_raw, list):
        roles = [str(item) for item in roles_raw]
    elif isinstance(roles_raw, str):
        roles = [part.strip() for part in roles_raw.split(",") if part.strip()]
    else:
        roles = [ROLE_ORG_ADMIN]
    return AuthPrincipal(
        subject=subject,
        token_fingerprint=_fingerprint(token),
        organization_id=organization_id,
        roles=normalize_roles(roles),
    )


def build_principal(token: str, settings: Settings) -> AuthPrincipal:
    registered = _principal_from_registry(token, settings)
    if registered is not None:
        return registered
    # Backward-compatible default: configured tokens act as org admins.
    return AuthPrincipal(
        subject="local-api-token",
        token_fingerprint=_fingerprint(token),
        organization_id="org-local",
        roles=frozenset({ROLE_ORG_ADMIN}),
    )


async def require_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer),
    ],
) -> AuthPrincipal:
    settings = _settings(request)
    if not settings.auth_required:
        principal = AuthPrincipal(
            subject="anonymous-dev",
            token_fingerprint="disabled",
            organization_id="org-local",
            roles=frozenset({ROLE_ORG_ADMIN}),
        )
        request.state.principal = principal
        return principal

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(
            "Authentication is required. Provide Authorization: Bearer <token>."
        )

    token = credentials.credentials.strip()
    allowed = settings.auth_token_set
    if not allowed:
        raise AuthenticationError(
            "Authentication is required but API_AUTH_TOKENS is empty. Configure at least one token."
        )
    if token not in allowed:
        raise AuthorizationError("The provided credentials are not authorized.")

    principal = build_principal(token, settings)
    request.state.principal = principal
    return principal


async def optional_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer),
    ],
) -> AuthPrincipal | None:
    settings = _settings(request)
    if not settings.auth_required:
        return AuthPrincipal(
            subject="anonymous-dev",
            token_fingerprint="disabled",
            organization_id="org-local",
            roles=frozenset({ROLE_ORG_ADMIN}),
        )
    if credentials is None:
        return None
    try:
        return await require_principal(request, credentials)
    except (AuthenticationError, AuthorizationError):
        return None


def parse_auth_principals(raw: str) -> dict[str, dict[str, Any]]:
    text = raw.strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("API_AUTH_PRINCIPALS must be a JSON object keyed by token.")
    return {
        str(token): value
        for token, value in payload.items()
        if isinstance(value, dict)
    }
