"""Bearer-token authentication with local principal registry.

Production Entra/JWT validation replaces this boundary. Until then, every document
route requires ``Authorization: Bearer <token>``. Optional ``API_AUTH_PRINCIPALS``
JSON maps tokens to subject, organization, and roles.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.core.authorization import ROLE_ORG_ADMIN, ROLE_REVIEWER, normalize_roles
from app.core.authorization import AuthPrincipal as AuthPrincipal
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


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    # PyJWT caches the JWK set and individual signing keys. The URL is trusted
    # operator configuration, never a request parameter.
    return PyJWKClient(url, cache_keys=True, lifespan=300)


# Only these roles may be the *target* of a reviewer assignment.
REVIEWER_CAPABLE_ROLES = frozenset({ROLE_REVIEWER, ROLE_ORG_ADMIN})


def principal_directory(settings: Settings) -> dict[str, dict[str, Any]]:
    """Subject -> {organization_id, roles} derived from the local principal registry.

    Multiple tokens may map to the same subject (e.g. rotation); their roles are
    merged. Returns an empty mapping when no local registry is configured.
    """
    directory: dict[str, dict[str, Any]] = {}
    for entry in settings.auth_principal_map.values():
        if not isinstance(entry, dict):
            continue
        subject = str(entry.get("subject") or "").strip()
        if not subject:
            continue
        organization_id = (
            str(entry.get("organization_id") or entry.get("organizationId") or "org-local").strip()
            or "org-local"
        )
        roles_raw = entry.get("roles")
        if isinstance(roles_raw, list):
            role_values = [str(item) for item in roles_raw]
        elif isinstance(roles_raw, str):
            role_values = [part.strip() for part in roles_raw.split(",") if part.strip()]
        else:
            role_values = [ROLE_ORG_ADMIN]
        try:
            roles = set(normalize_roles(role_values))
        except ValueError:
            continue
        existing = directory.get(subject)
        if existing is None:
            directory[subject] = {"organization_id": organization_id, "roles": roles}
        else:
            existing["roles"].update(roles)
    return directory


def validate_reviewer_assignment(
    settings: Settings,
    *,
    reviewer_subject: str,
    organization_id: str,
) -> None:
    """Fail closed unless the target is a real, same-organization, review-capable principal.

    When a local principal registry exists it is authoritative. When it does not,
    a production or Entra deployment cannot silently accept an unverifiable
    assignment (a real directory lookup requires enterprise identity), so it is
    rejected; a local development instance without a registry is allowed through.
    """
    subject = reviewer_subject.strip()
    if not subject:
        raise AuthorizationError("A reviewer subject is required.")
    directory = principal_directory(settings)
    if not directory:
        if settings.auth_required and (
            settings.auth_mode == "entra_jwt"
            or settings.app_env.casefold() == "production"
        ):
            raise AuthorizationError(
                "Reviewer directory is unavailable; the assignment cannot be validated."
            )
        return
    entry = directory.get(subject)
    if entry is None:
        raise AuthorizationError("The assigned reviewer is not a known principal.")
    if entry["organization_id"] != organization_id:
        raise AuthorizationError(
            "The assigned reviewer belongs to a different organization."
        )
    if not entry["roles"].intersection(REVIEWER_CAPABLE_ROLES):
        raise AuthorizationError(
            "The assigned principal is not permitted to review documents."
        )


async def _entra_principal(token: str, settings: Settings) -> AuthPrincipal:
    if not all(
        (
            settings.entra_tenant_id,
            settings.entra_client_id,
            settings.entra_issuer,
            settings.entra_jwks_url,
        )
    ):
        raise AuthenticationError("Enterprise authentication is not configured.")
    try:
        signing_key = await asyncio.to_thread(
            _jwks_client(settings.entra_jwks_url or "").get_signing_key_from_jwt,
            token,
        )
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.entra_client_id,
            issuer=settings.entra_issuer,
            options={"require": ["exp", "iat", "sub", "tid"]},
        )
    except (InvalidTokenError, PyJWKClientError, ValueError) as exc:
        raise AuthenticationError("The bearer token is invalid or expired.") from exc

    if str(claims.get("tid", "")) != settings.entra_tenant_id:
        raise AuthorizationError("The bearer token belongs to an unauthorized tenant.")
    subject = str(claims.get("oid") or claims.get("sub") or "").strip()
    organization_id = str(claims.get(settings.entra_organization_claim) or "").strip()
    roles_claim = claims.get(settings.entra_roles_claim)
    if isinstance(roles_claim, str):
        role_values = [roles_claim]
    elif isinstance(roles_claim, list):
        role_values = [str(role) for role in roles_claim]
    else:
        role_values = []
    if not subject or not organization_id or not role_values:
        raise AuthorizationError(
            "The bearer token is missing the required subject, organization, or role claims."
        )
    try:
        roles = normalize_roles(role_values)
    except ValueError as exc:
        raise AuthorizationError("The bearer token contains an unauthorized role.") from exc
    return AuthPrincipal(
        subject=subject,
        token_fingerprint=_fingerprint(token),
        organization_id=organization_id,
        roles=roles,
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
    if settings.auth_mode == "entra_jwt":
        principal = await _entra_principal(token, settings)
    else:
        allowed = settings.auth_token_set
        if not allowed:
            raise AuthenticationError(
                "Authentication is required but API_AUTH_TOKENS is empty. "
                "Configure at least one token."
            )
        # Constant-time comparison avoids leaking how much of a configured local
        # token matched. Local tokens remain a development/evaluation mechanism.
        if not any(hmac.compare_digest(token, candidate) for candidate in allowed):
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
