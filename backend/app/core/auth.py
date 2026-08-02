"""Bearer-token authentication for local PRD-ready deployments.

Production Entra/JWT validation replaces this boundary. Until then, every document
route requires ``Authorization: Bearer <token>`` matching ``API_AUTH_TOKENS``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.dependencies.services import ServiceContainer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    token_fingerprint: str


def _settings(request: Request) -> Settings:
    container: ServiceContainer = request.app.state.container
    return container.settings


def _fingerprint(token: str) -> str:
    return f"tok-{token[:4]}…{token[-4:]}" if len(token) >= 8 else "tok-short"


async def require_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthPrincipal:
    settings = _settings(request)
    if not settings.auth_required:
        return AuthPrincipal(subject="anonymous-dev", token_fingerprint="disabled")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication is required. Provide Authorization: Bearer <token>.")

    token = credentials.credentials.strip()
    allowed = settings.auth_token_set
    if not allowed:
        raise AuthenticationError(
            "Authentication is required but API_AUTH_TOKENS is empty. Configure at least one token."
        )
    if token not in allowed:
        raise AuthorizationError("The provided credentials are not authorized.")

    return AuthPrincipal(subject="local-api-token", token_fingerprint=_fingerprint(token))


async def optional_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthPrincipal | None:
    settings = _settings(request)
    if not settings.auth_required:
        return AuthPrincipal(subject="anonymous-dev", token_fingerprint="disabled")
    if credentials is None:
        return None
    try:
        return await require_principal(request, credentials)
    except (AuthenticationError, AuthorizationError):
        return None
