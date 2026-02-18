from __future__ import annotations

import os
from typing import Callable, Iterable

from fastapi.responses import ORJSONResponse

from .async_logger import async_logger


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self.max_bytes = _get_int("API_MAX_BODY_BYTES", 100 * 1024 * 1024)
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if b"content-length" in headers:
            try:
                if int(headers[b"content-length"]) > self.max_bytes:
                    await ORJSONResponse(
                        status_code=413,
                        content={"error": {"message": "Payload Too Large", "type": "request_too_large"}},
                    )(scope, receive, send)
                    return
            except Exception as e:
                await async_logger.log("app.middleware", "parse_content_length", "invalid_header", error=str(e))
        seen = 0
        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                body = msg.get("body", b"") or b""
                seen += len(body)
                if seen > self.max_bytes:
                    raise _PayloadTooLarge()
            return msg
        try:
            await self.app(scope, limited_receive, send)
        except _PayloadTooLarge:
            await async_logger.log("app.middleware", "body_size_limit", "payload_too_large", max_bytes=self.max_bytes)
            await ORJSONResponse(
                status_code=413,
                content={"error": {"message": "Payload Too Large", "type": "request_too_large"}},
            )(scope, receive, send)


class BearerAuthMiddleware:
    def __init__(self, app, exempt_paths: Iterable[str] = ("/docs", "/openapi.json", "/health")):
        self.app = app
        self.token = os.getenv("API_BEARER_TOKEN", "").strip()
        self.exempt = set(exempt_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path in self.exempt or path.startswith("/docs/"):
            await self.app(scope, receive, send)
            return
        if not self.token:
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = (headers.get(b"authorization") or b"").decode("utf-8", "ignore")
        ok = auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == self.token
        if not ok and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if not ok:
            await ORJSONResponse(
                status_code=401,
                content={"error": {"message": "Unauthorized", "type": "authentication_error"}},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


class _PayloadTooLarge(Exception):
    pass


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default
