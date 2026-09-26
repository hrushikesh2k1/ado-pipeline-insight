"""HTTP hardening: request-size limit, security headers, and the App Service Easy Auth gate."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

HEALTH_PATH = "/api/v1/health"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class RequestSizeLimit:
    """Reject request bodies larger than max_bytes, both by Content-Length and while streaming."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": "Request body too large."}, status_code=413)
        await response(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


class SecurityHeaders:
    def __init__(self, app: ASGIApp, csp: bool):
        self.app = app
        self.csp = csp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = dict(SECURITY_HEADERS)
                if self.csp:
                    extra["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                if path.startswith("/api/"):
                    extra["Cache-Control"] = "no-store"
                for key, value in extra.items():
                    if key.lower().encode() not in present:
                        headers.append((key.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class EasyAuthGate:
    """Require the App Service Easy Auth principal header on /api/ routes (the health probe stays open).

    App Service strips client-supplied X-MS-* identity headers when Authentication is enabled, so the header can
    only be present for requests the platform already authenticated. Enable Authentication on the app first.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/") and scope["path"] != HEALTH_PATH and scope["method"] != "OPTIONS":
            if not Request(scope).headers.get("x-ms-client-principal-id"):
                response: Response = JSONResponse({"detail": "Authentication required."}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

