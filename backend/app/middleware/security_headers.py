from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Applied to every API response. The API returns JSON and file downloads only,
# so it never needs to execute scripts or be framed. A locked-down policy keeps
# extracted/translated document bodies from being embedded, sniffed, or leaked
# through referrers if a response is ever opened directly in a browser.
_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# The interactive API documentation (only enabled in local development) loads
# Swagger/ReDoc assets from a CDN and uses inline bootstrap scripts, so it needs
# a relaxed policy. It is never served in production builds.
_DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json")
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        for name, value in _BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        path = request.url.path
        is_docs = any(path.startswith(prefix) for prefix in _DOCS_PREFIXES)
        response.headers.setdefault(
            "Content-Security-Policy", _DOCS_CSP if is_docs else _API_CSP
        )
        return response
