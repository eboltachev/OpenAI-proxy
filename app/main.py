from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .async_logger import async_logger
from .config import ConfigProvider, config_cache_ttl_s
from .errors import openai_error
from .middleware import BodySizeLimitMiddleware, BearerAuthMiddleware, RateLimitMiddleware, auth_required, bearer_token
from .routers import internal as internal_router
from .routers.proxy import router as proxy_router
from .routers.public import router as public_router
from .routers.realtime import router as realtime_router
from .stream_json import iter_stream_json
from .upstream import timeout_s, tls_verify


@asynccontextmanager
async def lifespan(app: FastAPI):
    if auth_required() and not bearer_token():
        raise RuntimeError("API_AUTH_REQUIRED=1 but API_BEARER_TOKEN is empty")
    await async_logger.start()
    app.state.http_client = httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify())
    app.state.caps_client = httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify())
    app.state.config_provider = ConfigProvider(ttl_s=config_cache_ttl_s())
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await app.state.caps_client.aclose()
        await async_logger.stop()


app = FastAPI(
    title="OpenAI Proxy",
    version="0.1.0",
    description="OpenAI-compatible proxy router for vLLM / Ollama / other endpoints.",
    lifespan=lifespan,
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BearerAuthMiddleware, exempt_paths=("/docs", "/openapi.json", "/health", "/v1/models"))

app.include_router(public_router)
app.include_router(realtime_router)
app.include_router(proxy_router)
app.include_router(internal_router.router)


async def stream_from_redis(stream_key: str):
    redis_client = getattr(app.state, "redis_stream_client", None)
    if redis_client is None:
        return openai_error(503, "Redis stream client is not configured", code="redis_not_configured")

    async def sse_iter():
        async for item in iter_stream_json(redis_client, stream_key):
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(sse_iter(), media_type="text/event-stream")


__all__ = ["app", "stream_from_redis"]
