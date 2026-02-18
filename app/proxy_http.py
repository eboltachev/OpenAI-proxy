from __future__ import annotations

from typing import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse, ORJSONResponse

from .config import Upstream
from .errors import openai_error
from .upstream import join_upstream_url, timeout_s, tls_verify, caps_cache


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


def _provider_allowlist(u: Upstream) -> set[str] | None:
    b = u.base_url.lower()
    if "deepinfra" in b:
        return DEEPINFRA_ALLOWLIST
    # Ollama часто на 11434
    if ":11434" in b or "ollama" in b:
        return OPENAI_ALLOWLIST
    return None


async def ensure_route_supported(u: Upstream, incoming_path: str) -> ORJSONResponse | None:
    caps = await caps_cache.get(u)
    if caps.paths is not None:
        if incoming_path not in caps.paths:
            return openai_error(404, f"Route not supported by upstream: {incoming_path}", code="route_not_found")
        return None

    allow = _provider_allowlist(u)
    if allow is not None and incoming_path not in allow:
        return openai_error(404, f"Route not supported by upstream: {incoming_path}", code="route_not_found")

    # allow is None => неизвестный upstream: не блокируем заранее, проверим по факту (404 от upstream)
    return None


def _filtered_headers(request: Request, upstream: Upstream) -> dict[str, str]:
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP:
            continue
        if lk == "authorization":
            # входной токен прокси НЕ должен уходить в upstream
            continue
        headers[k] = v

    if upstream.api_key:
        headers["Authorization"] = f"Bearer {upstream.api_key}"

    # полезно для диагностики
    headers["X-Proxy-Model"] = upstream.model
    return headers


async def proxy_http(
    request: Request,
    upstream: Upstream,
    body_stream: AsyncIterator[bytes],
) -> StreamingResponse:
    incoming_path = request.url.path
    qs = request.url.query

    pre = await ensure_route_supported(upstream, incoming_path)
    if pre is not None:
        return pre  # type: ignore[return-value]

    url = join_upstream_url(upstream.base_url, incoming_path)
    if qs:
        url = f"{url}?{qs}"

    headers = _filtered_headers(request, upstream)

    async with httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify()) as client:
        try:
            async with client.stream(
                method=request.method,
                url=url,
                headers=headers,
                content=body_stream if request.method in ("POST", "PUT", "PATCH") else None,
            ) as r:
                # если upstream явно говорит "не найдено" — вернём OpenAI-style ошибку
                if r.status_code == 404:
                    return openai_error(404, f"Upstream returned 404 for {incoming_path}", code="upstream_404")  # type: ignore[return-value]

                # копируем заголовки ответа (без hop-by-hop)
                resp_headers = {}
                for k, v in r.headers.items():
                    if k.lower() in HOP_BY_HOP:
                        continue
                    resp_headers[k] = v

                resp_headers["X-Proxy-Upstream"] = upstream.base_url

                async def iter_resp():
                    async for chunk in r.aiter_raw():
                        yield chunk

                return StreamingResponse(
                    iter_resp(),
                    status_code=r.status_code,
                    headers=resp_headers,
                    media_type=r.headers.get("content-type"),
                )
        except httpx.TimeoutException:
            return openai_error(504, f"Upstream timeout: {upstream.base_url}", err_type="timeout_error")  # type: ignore[return-value]
        except httpx.RequestError as e:
            return openai_error(502, f"Upstream request error: {e!s}", err_type="api_error")  # type: ignore[return-value]

