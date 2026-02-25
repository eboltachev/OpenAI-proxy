from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import ConfigProvider
from ..upstream import join_upstream_url
from ..errors import openai_error
from ..async_logger import async_logger

router = APIRouter()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _cfg(request: Request) -> dict:
    provider: ConfigProvider | None = getattr(request.app.state, "config_provider", None)
    if provider is None:
        return {}
    return provider.get()


def _public_health_details_enabled() -> bool:
    return _env_bool("API_PUBLIC_HEALTH_DETAILS", False)


async def _build_health_payload(request: Request, *, include_details: bool) -> dict:
    cfg = _cfg(request)
    by_upstream: dict[str, list[str]] = defaultdict(list)
    for m, u in cfg.items():
        by_upstream[u.base_url].append(m)
    results = {}
    overall_ok = True
    client = request.app.state.http_client

    for base_url, models in by_upstream.items():
        t0 = time.time()
        ok = False
        err = None

        url_health = join_upstream_url(base_url, "/health")
        try:
            r = await client.get(url_health)
            ok = r.status_code == 200
            if not ok:
                err = f"/health -> {r.status_code}"
        except Exception as e:
            err = f"/health error: {e!s}"
            await async_logger.log("app.main", "health_check", "error", base_url=base_url, endpoint="/health", error=str(e))

        if not ok:
            url_models = join_upstream_url(base_url, "/v1/models")
            try:
                r = await client.get(url_models)
                ok = r.status_code == 200
                if not ok:
                    err = (err or "") + f"; /v1/models -> {r.status_code}"
            except Exception as e:
                err = (err or "") + f"; /v1/models error: {e!s}"
                await async_logger.log("app.main", "health_check", "error", base_url=base_url, endpoint="/v1/models", error=str(e))

        dt_ms = int((time.time() - t0) * 1000)
        results[base_url] = {"ok": ok, "latency_ms": dt_ms, "models": models, "error": err}
        overall_ok = overall_ok and ok

    status = "ok" if overall_ok else "degraded"
    if include_details:
        return {"status": status, "upstreams": results}
    return {"status": status}


@router.get("/health")
async def health(request: Request):
    try:
        payload = await _build_health_payload(request, include_details=_public_health_details_enabled())
    except Exception as e:
        return openai_error(500, f"Configuration error: {e}", code="config_error")
    return JSONResponse(content=payload)


@router.get("/internal/health")
async def health_internal(request: Request):
    try:
        payload = await _build_health_payload(request, include_details=True)
    except Exception as e:
        return openai_error(500, f"Configuration error: {e}", code="config_error")
    return JSONResponse(content=payload)


@router.get("/v1/models")
async def list_models(request: Request):
    try:
        cfg = _cfg(request)
    except Exception as e:
        return openai_error(500, f"Configuration error: {e}", code="config_error")
    data = [{"id": model, "object": "model", "owned_by": "proxy"} for model in sorted(cfg.keys())]
    return JSONResponse(content={"object": "list", "data": data})
