from __future__ import annotations

from fastapi import APIRouter, Request

from ..async_logger import async_logger
from ..config import ConfigProvider
from ..errors import openai_error
from ..proxy_http import proxy_http
from ..sniff import sniff_model_and_stream

router = APIRouter()

PROXY_PATHS = [
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/responses",
    "/v1/audio/transcriptions",
    "/v1/audio/translations",
    "/tokenize",
    "/detokenize",
    "/pooling",
    "/classify",
    "/score",
    "/rerank",
    "/v1/rerank",
    "/v2/rerank",
]


async def route_and_proxy(request: Request):
    provider: ConfigProvider = request.app.state.config_provider
    try:
        cfg = provider.get()
    except Exception as e:
        return openai_error(500, f"Configuration error: {e}", code="config_error")

    try:
        model, body_stream = await sniff_model_and_stream(request)
    except ValueError as e:
        await async_logger.log("app.proxy", "route_request", "model_not_found", error=str(e), path=request.url.path)
        return openai_error(400, str(e), code="model_not_found")

    upstream = cfg.get(model)
    if not upstream:
        await async_logger.log("app.proxy", "route_request", "unknown_model", model=model, path=request.url.path)
        return openai_error(400, f"Unknown model: {model}", code="unknown_model")

    await async_logger.log(
        "app.proxy",
        "route_request",
        "upstream_selected",
        model=model,
        upstream=upstream.base_url,
        path=request.url.path,
    )
    return await proxy_http(request, upstream, body_stream)


for path in PROXY_PATHS:
    router.add_api_route(path, route_and_proxy, methods=["POST"])
