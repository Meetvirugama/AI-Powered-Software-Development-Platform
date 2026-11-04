"""Security headers added to every HTTP response.
Owner: Sukun — W1, Day 6 (API Security)

    X-Content-Type-Options: nosniff                       — always
    X-Frame-Options: DENY                                 — always
    Referrer-Policy: strict-origin-when-cross-origin      — always
    Content-Security-Policy                               — always (unless docs UI)
    Strict-Transport-Security                             — only when the request came over HTTPS

This is a plain ASGI middleware (not BaseHTTPMiddleware) so it also covers
responses produced by other middleware — 401s from JWTMiddleware, 429s from
the rate limiter and CORS preflight replies. Register it LAST in main.py so it
is the outermost user middleware. (Starlette's own ServerErrorMiddleware still
sits outside it, so a crash-level 500 is the one response without these
headers; the 500 body is a generic JSON error and carries no page content.)
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS_VALUE = "max-age=31536000; includeSubDomains"
CSP_VALUE = "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
REFERRER_POLICY_VALUE = "strict-origin-when-cross-origin"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, trust_proxy_headers: bool = False) -> None:
        self.app = app
        self.trust_proxy_headers = trust_proxy_headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = self._is_https(scope)
        path = scope.get("path", "")
        is_docs_ui = path in ("/docs", "/redoc")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = REFERRER_POLICY_VALUE
                if not is_docs_ui and "content-security-policy" not in headers:
                    headers["Content-Security-Policy"] = CSP_VALUE
                if is_https:
                    headers["Strict-Transport-Security"] = HSTS_VALUE
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _is_https(self, scope: Scope) -> bool:
        if scope.get("scheme") == "https":
            return True
        if self.trust_proxy_headers:
            # Behind a TLS-terminating load balancer the app sees plain HTTP.
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-proto":
                    return value.decode("latin-1").split(",")[0].strip().lower() == "https"
        return False
