"""Pure-ASGI middleware (not ``BaseHTTPMiddleware``, which would buffer streamed responses)."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
_PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=()"
_HSTS = "max-age=31536000"


class SecurityHeadersMiddleware:
    """Adds hardening headers to every response and stops browsers caching API data.

    The Content-Security-Policy allows only the dashboard's own scripts and styles (no inline
    code), which is what stops an injected script from running even if one slipped into a page.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap the response so hardening headers are added."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith(("/api/", "/v1/"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Content-Security-Policy", _CSP)
                headers.setdefault("Permissions-Policy", _PERMISSIONS)
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", _HSTS)
                if is_api:
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class OriginCheckMiddleware:
    """Rejects cross-site browser writes to ``/api/*`` (defence in depth next to CSRF tokens).

    Browsers always send ``Origin`` and ``Sec-Fetch-Site`` on cross-site writes. Programs
    such as curl send neither and are unaffected; they authenticate with a token anyway.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = {o.lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Block cross-site writes; pass everything else through."""
        if (
            scope["type"] == "http"
            and scope["method"] in _UNSAFE_METHODS
            and scope["path"].startswith("/api/")
            and not self._acceptable(Headers(scope=scope))
        ):
            response = JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _acceptable(self, headers: Headers) -> bool:
        fetch_site = headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site not in _ALLOWED_FETCH_SITES:
            return False
        origin = headers.get("origin")
        if origin is None:
            return True
        if origin.rstrip("/").lower() in self.allowed_origins:
            return True
        return urlsplit(origin).netloc.lower() == headers.get("host", "").lower()
