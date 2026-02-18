from __future__ import annotations

from typing import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse, ORJSONResponse
from starlette.background import BackgroundTask

from .config import Upstream
from .errors import openai_error
from .async_logger import async_logger
from .upstream import (
    join_upstream_url, timeout_s, tls_verify, 
    caps_cache, http_fallback_url_on_ssl_error
)


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}

OPENAI_ALLOWLIST = {
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/models",
    "/v1/responses",
    "/v1/images/generations",
}

DEEPINFRA_ALLOWLIST = {
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/models",
    "/v1/responses",
    "/v1/images/generations",
}


async def proxy_http(
    request: Request,
    upstream: Upstream,
    body_stream: AsyncIterator[bytes],
) -> StreamingResponse:
    incoming_path = request.url.path
    qs = request.url.query
    pre = await ensure_route_supported(upstream, incoming_path)
    if pre is not None:
        return pre
    url = join_upstream_url(upstream.base_url, incoming_path)
    if qs:
        url = f"{url}?{qs}"
    headers = _filtered_headers(request, upstream)
    client = httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify())
    req = client.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=body_stream if request.method in ("POST", "PUT", "PATCH") else None,
    )
    try:
        r = await client.send(req, stream=True)
    except httpx.TimeoutException:
        await async_logger.log("app.proxy_http", "forward_request", "timeout", upstream=upstream.base_url, path=incoming_path)
        await client.aclose()
        return openai_error(504, f"Upstream timeout: {upstream.base_url}", err_type="timeout_error")  # type: ignore[return-value]
    except httpx.RequestError as e:
        await async_logger.log("app.proxy_http", "forward_request", "request_error", upstream=upstream.base_url, path=incoming_path, error=str(e))
        fallback_url = http_fallback_url_on_ssl_error(url, e)
        if fallback_url is None:
            await client.aclose()
            return openai_error(502, f"Upstream request error: {e!s}", err_type="api_error")  # type: ignore[return-value]
        fallback_req = client.build_request(
            method=request.method,
            url=fallback_url,
            headers=headers,
            content=body_stream if request.method in ("POST", "PUT", "PATCH") else None,
        )
        try:
            r = await client.send(fallback_req, stream=True)
        except httpx.TimeoutException:
            await async_logger.log("app.proxy_http", "forward_request_fallback", "timeout", upstream=upstream.base_url, path=incoming_path)
            await client.aclose()
            return openai_error(504, f"Upstream timeout: {upstream.base_url}", err_type="timeout_error")  # type: ignore[return-value]
        except httpx.RequestError as e2:
            await async_logger.log("app.proxy_http", "forward_request_fallback", "request_error", upstream=upstream.base_url, path=incoming_path, error=str(e2))
            await client.aclose()
            return openai_error(502, f"Upstream request error: {e!s}", err_type="api_error")  # type: ignore[return-value]
    if r.status_code == 404:
        await async_logger.log("app.proxy_http", "forward_request", "upstream_404", upstream=upstream.base_url, path=incoming_path)
        await r.aclose()
        await client.aclose()
        return openai_error(404, f"Upstream returned 404 for {incoming_path}", code="upstream_404")  # type: ignore[return-value]
    resp_headers = {}
    for k, v in r.headers.items():
        if k.lower() in HOP_BY_HOP:
            continue
        resp_headers[k] = v
    resp_headers["X-Proxy-Upstream"] = upstream.base_url

    async def close_upstream() -> None:
        await r.aclose()
        await client.aclose()

    return StreamingResponse(
        r.aiter_raw(),
        status_code=r.status_code,
        headers=resp_headers,
        media_type=r.headers.get("content-type"),
        background=BackgroundTask(close_upstream),
    )


async def ensure_route_supported(u: Upstream, incoming_path: str) -> ORJSONResponse | None:
    caps = await caps_cache.get(u)
    if caps.paths is not None:
        if incoming_path not in caps.paths:
            return openai_error(404, f"Route not supported by upstream: {incoming_path}", code="route_not_found")
        return None
    allow = _provider_allowlist(u)
    if allow is not None and incoming_path not in allow:
        return openai_error(404, f"Route not supported by upstream: {incoming_path}", code="route_not_found")
    return None


def _filtered_headers(request: Request, upstream: Upstream) -> dict[str, str]:
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP:
            continue
        if lk == "authorization":
            continue
        headers[k] = v
    if upstream.api_key:
        headers["Authorization"] = f"Bearer {upstream.api_key}"
    headers["X-Proxy-Model"] = upstream.model
    return headers


def _provider_allowlist(u: Upstream) -> set[str] | None:
    b = u.base_url.lower()
    if "deepinfra" in b:
        return DEEPINFRA_ALLOWLIST
    if ":11434" in b or "ollama" in b:
        return OPENAI_ALLOWLIST
    return None
