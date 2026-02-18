from __future__ import annotations

import os
import time
from collections import defaultdict

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import ORJSONResponse

from .config import load_config, Upstream
from .errors import openai_error
from .middleware import BodySizeLimitMiddleware, BearerAuthMiddleware
from .shiff import sniff_model_and_stream
from .proxy_http import proxy_http
from .proxy_ws import proxy_realtime_ws
from .upstream import join_upstream_url, timeout_s, tls_verify


app = FastAPI(
    title="OpenAI Proxy",
    version="0.1.0",
    description="OpenAI-compatible proxy router for vLLM / Ollama / other endpoints.",
)

# middleware: сначала лимит, потом auth
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(BearerAuthMiddleware, exempt_paths=("/docs", "/openapi.json", "/health", "/v1/models"))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


@app.get("/health")
async def health():
    cfg = load_config()
    by_upstream: dict[str, list[str]] = defaultdict(list)
    for m, u in cfg.items():
        by_upstream[u.base_url].append(m)

    results = {}
    overall_ok = True

    async with httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify()) as client:
        for base_url, models in by_upstream.items():
            t0 = time.time()
            ok = False
            err = None

            # 1) пробуем /health
            url_health = join_upstream_url(base_url, "/health")
            try:
                r = await client.get(url_health)
                ok = (r.status_code == 200)
                if not ok:
                    err = f"/health -> {r.status_code}"
            except Exception as e:
                err = f"/health error: {e!s}"

            # 2) если не ок — пробуем /v1/models (OpenAI-style)
            if not ok:
                url_models = join_upstream_url(base_url, "/v1/models")
                try:
                    r = await client.get(url_models)
                    ok = (r.status_code == 200)
                    if not ok:
                        err = (err or "") + f"; /v1/models -> {r.status_code}"
                except Exception as e:
                    err = (err or "") + f"; /v1/models error: {e!s}"

            dt_ms = int((time.time() - t0) * 1000)
            results[base_url] = {
                "ok": ok,
                "latency_ms": dt_ms,
                "models": models,
                "error": err,
            }
            overall_ok = overall_ok and ok

    status = "ok" if overall_ok else "degraded"
    return ORJSONResponse(content={"status": status, "upstreams": results})


@app.get("/v1/models")
async def list_models():
    cfg = load_config()
    data = []
    for model in sorted(cfg.keys()):
        data.append(
            {
                "id": model,
                "object": "model",
                "owned_by": "proxy",
            }
        )
    return ORJSONResponse(content={"object": "list", "data": data})


@app.websocket("/v1/realtime")
async def realtime(ws: WebSocket):
    cfg = load_config()
    model = ws.query_params.get("model")
    if not model or model not in cfg:
        await ws.close(code=4404)
        return
    await proxy_realtime_ws(ws, cfg[model])


async def _route_and_proxy(request: Request):
    cfg = load_config()

    try:
        model, body_stream = await sniff_model_and_stream(request)
    except ValueError as e:
        return openai_error(400, str(e), code="model_not_found")

    upstream = cfg.get(model)
    if not upstream:
        return openai_error(400, f"Unknown model: {model}", code="unknown_model")

    return await proxy_http(request, upstream, body_stream)


# --- vLLM/OpenAI ключевые роуты (чтобы красиво отображались в /docs) ---

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/completions")
async def completions(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/embeddings")
async def embeddings(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/responses")
async def responses(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/audio/translations")
async def audio_translations(request: Request):
    return await _route_and_proxy(request)

# vLLM custom endpoints :contentReference[oaicite:4]{index=4}
@app.post("/tokenize")
async def tokenize(request: Request):
    return await _route_and_proxy(request)

@app.post("/detokenize")
async def detokenize(request: Request):
    return await _route_and_proxy(request)

@app.post("/pooling")
async def pooling(request: Request):
    return await _route_and_proxy(request)

@app.post("/classify")
async def classify(request: Request):
    return await _route_and_proxy(request)

@app.post("/score")
async def score(request: Request):
    return await _route_and_proxy(request)

@app.post("/rerank")
async def rerank(request: Request):
    return await _route_and_proxy(request)

@app.post("/v1/rerank")
async def rerank_v1(request: Request):
    return await _route_and_proxy(request)

@app.post("/v2/rerank")
async def rerank_v2(request: Request):
    return await _route_and_proxy(request)


# Catch-all: если в vLLM появятся новые роуты — прокси их тоже пробросит
@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def catch_all(request: Request, full_path: str):
    # /health и /v1/models уже определены выше
    return await _route_and_proxy(request)

