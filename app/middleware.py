from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Iterable

from fastapi.responses import JSONResponse

from .async_logger import async_logger


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def auth_required() -> bool:
    return _env_bool("API_AUTH_REQUIRED", True)


def bearer_token() -> str:
    return os.getenv("API_BEARER_TOKEN", "").strip()


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
                    await JSONResponse(
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
            await JSONResponse(
                status_code=413,
                content={"error": {"message": "Payload Too Large", "type": "request_too_large"}},
            )(scope, receive, send)


class BearerAuthMiddleware:
    def __init__(self, app, exempt_paths: Iterable[str] = ("/docs", "/openapi.json", "/health")):
        self.app = app
        self.token = bearer_token()
        self.required = auth_required()
        self.exempt = set(exempt_paths)

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path in self.exempt or path.startswith("/docs/"):
            await self.app(scope, receive, send)
            return

        if not self.required:
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = (headers.get(b"authorization") or b"").decode("utf-8", "ignore")
        ok = auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == self.token

        if scope_type == "http":
            if not ok and scope.get("method") == "OPTIONS":
                await self.app(scope, receive, send)
                return
            if not ok:
                await JSONResponse(
                    status_code=401,
                    content={"error": {"message": "Unauthorized", "type": "authentication_error"}},
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        if not ok:
            await send({"type": "websocket.close", "code": 4401})
            return
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self.rps = _get_int("API_RATE_LIMIT_RPS", 0)
        self.burst = _get_int("API_RATE_LIMIT_BURST", 0)
        self._buckets: dict[str, tuple[float, float]] = defaultdict(lambda: (0.0, float(self.burst or self.rps)))

    async def __call__(self, scope, receive, send):
        if self.rps <= 0:
            await self.app(scope, receive, send)
            return
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        key = client[0] if client else "unknown"
        now = time.monotonic()
        last_ts, tokens = self._buckets[key]
        cap = float(self.burst or self.rps)
        tokens = min(cap, tokens + (now - last_ts) * self.rps)
        if tokens < 1.0:
            await async_logger.log("app.middleware", "rate_limit", "hit", client=key, path=scope.get("path"))
            await JSONResponse(
                status_code=429,
                content={"error": {"message": "Too Many Requests", "type": "rate_limit_error"}},
            )(scope, receive, send)
            self._buckets[key] = (now, tokens)
            return
        self._buckets[key] = (now, tokens - 1.0)
        await self.app(scope, receive, send)


class _PayloadTooLarge(Exception):
    pass


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default
