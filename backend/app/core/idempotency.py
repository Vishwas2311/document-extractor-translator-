"""Helpers for request idempotency.

The route layer uses these to turn a client ``Idempotency-Key`` plus the calling
principal into a stable scope string, and to fingerprint the meaningful parts of
a request so an accidental replay is detected while a deliberate reuse of the key
with a *different* request is rejected.
"""

from __future__ import annotations

import hashlib

from app.core.authorization import AuthPrincipal

# Bound so a hostile client cannot store unbounded key material.
MAX_IDEMPOTENCY_KEY_LENGTH = 200


def normalize_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    return key[:MAX_IDEMPOTENCY_KEY_LENGTH]


def request_fingerprint(*parts: str | None) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update((part or "").encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def idempotency_scope(principal: AuthPrincipal, operation: str, key: str) -> str:
    # Delimited concatenation (f"{org}:{subject}:{op}:{key}") would let two
    # distinct (org, subject, op, key) tuples collide on the same scope
    # string whenever a ':' lands differently across the components -
    # organization_id/subject come from operator-configured principals or JWT
    # claims and are not restricted to a colon-free charset. A collision here
    # means one principal's reservation can be read as another's, and in the
    # fingerprint-match case replay a different principal's cached response.
    # Hashing with request_fingerprint's null-byte-delimited scheme removes
    # the ambiguity entirely.
    return request_fingerprint(principal.organization_id, principal.subject, operation, key)
