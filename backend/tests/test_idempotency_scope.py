"""Regression: idempotency_scope() must not let two distinct principals collide
onto the same scope string.

Before this fix, the scope was built by naive colon-delimited concatenation
(f"{org}:{subject}:{op}:{key}"). organization_id and subject come from
operator-configured principals or JWT claims and are not restricted to a
colon-free charset, so two different (org, subject) pairs could concatenate
to the identical string - e.g. org="A", subject="B:C" vs. org="A:B",
subject="C". A collision here means one principal's idempotency reservation
is indistinguishable from another's, and in the fingerprint-match case would
replay a different principal's cached response (including its resource_id).

Confirmed by code review on 2026-08-12.
"""

from app.core.authorization import AuthPrincipal
from app.core.idempotency import idempotency_scope


def test_colon_containing_components_do_not_collide() -> None:
    principal_a = AuthPrincipal(subject="B:C", token_fingerprint="x", organization_id="A")
    principal_b = AuthPrincipal(subject="C", token_fingerprint="x", organization_id="A:B")

    scope_a = idempotency_scope(principal_a, "document.upload", "key")
    scope_b = idempotency_scope(principal_b, "document.upload", "key")

    assert scope_a != scope_b


def test_same_principal_and_key_is_stable() -> None:
    principal = AuthPrincipal(subject="user-1", token_fingerprint="x", organization_id="org-1")

    first = idempotency_scope(principal, "document.upload", "key-abc")
    second = idempotency_scope(principal, "document.upload", "key-abc")

    assert first == second
