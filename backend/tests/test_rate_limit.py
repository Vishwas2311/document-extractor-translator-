"""Exercises the real `RateLimitMiddleware.dispatch` logic - not a mock - by calling it
directly enough times to actually trip the limit, the way it would in production."""

import json
import time

from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware


def _request(path: str = "/api/v1/documents", client_host: str = "127.0.0.1") -> Request:
    request = Request(
        {"type": "http", "path": path, "headers": [], "client": (client_host, 12345)}
    )
    request.state.request_id = "req-rl-test"
    return request


def _bare_request(
    path: str = "/api/v1/documents", client_host: str = "127.0.0.1"
) -> Request:
    """A request without a pre-set request_id, as it arrives from the transport."""
    return Request(
        {"type": "http", "path": path, "headers": [], "client": (client_host, 12345)}
    )


async def _call_next(request: Request) -> Response:
    return Response("ok", status_code=200)


async def test_rate_limit_allows_requests_under_the_limit() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=3)
    )
    for _ in range(3):
        response = await middleware.dispatch(_request(), _call_next)
        assert response.status_code == 200


async def test_rate_limit_returns_429_once_the_window_is_exceeded() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=2)
    )
    for _ in range(2):
        response = await middleware.dispatch(_request(), _call_next)
        assert response.status_code == 200

    response = await middleware.dispatch(_request(), _call_next)

    assert response.status_code == 429
    body = json.loads(bytes(response.body))
    assert body["code"] == "rate_limit_exceeded"
    assert body["retryable"] is True
    assert body["request_id"] == "req-rl-test"
    # The generic per-status message, not raw internals - safe to show as-is.
    assert body["message"] == "Too many requests. Slow down and retry shortly."


async def test_rate_limit_tracks_separate_clients_independently() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=1)
    )
    first_client = await middleware.dispatch(_request(client_host="10.0.0.1"), _call_next)
    second_client = await middleware.dispatch(_request(client_host="10.0.0.2"), _call_next)
    assert first_client.status_code == 200
    assert second_client.status_code == 200

    third_from_first_client = await middleware.dispatch(
        _request(client_host="10.0.0.1"), _call_next
    )
    assert third_from_first_client.status_code == 429


async def test_rate_limit_skips_the_liveness_endpoint() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=1)
    )
    for _ in range(5):
        response = await middleware.dispatch(_request(path="/api/v1/health/live"), _call_next)
        assert response.status_code == 200


async def test_rate_limit_disabled_when_limit_is_zero() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=0)
    )
    for _ in range(10):
        response = await middleware.dispatch(_request(), _call_next)
        assert response.status_code == 200


def test_request_context_middleware_executes_before_the_rate_limiter() -> None:
    # add_middleware prepends, so RequestContextMiddleware must be *later* in
    # main.py for it to execute first and stamp request_id before any 429.
    from app.main import app

    classes: list[object] = [middleware.cls for middleware in app.user_middleware]
    assert classes.index(RequestContextMiddleware) < classes.index(RateLimitMiddleware)


async def test_429_carries_a_real_request_id_and_header() -> None:
    """Chains the two middlewares in the app's execution order (RequestContext
    outermost) and confirms the rate limiter's 429 gets a real request id in the
    body and the x-request-id response header."""
    limiter = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=1)
    )
    context = RequestContextMiddleware(app=None)  # type: ignore[arg-type]

    async def through_limiter(request: Request) -> Response:
        return await limiter.dispatch(request, _call_next)

    first = await context.dispatch(_bare_request(), through_limiter)
    assert first.status_code == 200

    second = await context.dispatch(_bare_request(), through_limiter)
    assert second.status_code == 429
    body = json.loads(bytes(second.body))
    assert body["request_id"] != "unknown"
    assert second.headers["x-request-id"] == body["request_id"]


async def test_rate_limit_evicts_expired_client_windows() -> None:
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(auth_required=False, rate_limit_per_minute=5)
    )
    response = await middleware.dispatch(_request(client_host="10.0.0.9"), _call_next)
    assert response.status_code == 200
    stale_key = next(iter(middleware._hits))
    # Age the stale client's hits past the 60s window and force a sweep.
    middleware._hits[stale_key][0] = time.monotonic() - 120
    middleware._last_sweep = time.monotonic() - 3600

    await middleware.dispatch(_request(client_host="10.0.0.10"), _call_next)

    assert stale_key not in middleware._hits
