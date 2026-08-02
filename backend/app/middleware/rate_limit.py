"""Simple in-process rate limiting for local PRD-ready deployments."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limit = self.settings.rate_limit_per_minute
        if limit <= 0:
            return await call_next(request)

        path = request.url.path
        # Skip liveness only; readiness and documents are limited.
        if path.endswith("/health") or path.endswith("/health/live"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        key = f"{client}:{path.split('/documents')[0]}"
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Slow down and retry shortly.",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                    "retryable": True,
                    "details": {},
                },
            )
        window.append(now)
        return await call_next(request)
