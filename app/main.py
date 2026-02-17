from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

ROUTES_CONFIG_PATH = Path(os.getenv("ROUTES_CONFIG_PATH", "/app/config/routes.yaml"))
PROXY_SECRET_KEY = os.getenv("PROXY_SECRET_KEY")

app = FastAPI(title="Dynamic vLLM Proxy", version="1.6.0")


class ConfigError(RuntimeError):
    """Ошибка чтения/валидации конфигурации."""


@dataclass(frozen=True)
class RouteConfig:
    path: str
    path_regex: re.Pattern[str]
    methods: list[str]
    upstream_url: str
    upstream_key: str
    upstream_key_header: str
    upstream_key_prefix: str


def _get_routes_config_path() -> Path:
    return Path(os.getenv("ROUTES_CONFIG_PATH", str(ROUTES_CONFIG_PATH)))


def _get_proxy_secret_key() -> str | None:
    return os.getenv("PROXY_SECRET_KEY", PROXY_SECRET_KEY)


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _compile_path_pattern(path: str) -> re.Pattern[str]:
    pattern = re.sub(r"\{([^/{}]+)\}", r"(?P<\1>[^/]+)", path)
    return re.compile(rf"^{pattern}$")


def _extract_base_url(upstream_url: str) -> str:
    parsed = urlsplit(upstream_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid upstream URL for base extraction: {upstream_url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_request_timeout(request: Request) -> float | None:
    timeout_raw = request.query_params.get("timeout") or request.headers.get("x-timeout-seconds")
    if timeout_raw is None:
        return None
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid timeout value") from exc
    if timeout <= 0:
        raise HTTPException(status_code=422, detail="Timeout must be > 0")
    return timeout


def _load_routes_config() -> list[RouteConfig]:
    routes_config_path = _get_routes_config_path()
    if not routes_config_path.exists():
        raise ConfigError(f"Config file not found: {routes_config_path}")

    try:
        data = yaml.safe_load(routes_config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {routes_config_path}: {exc}") from exc

    routes = data.get("routes")
    if not isinstance(routes, list):
        raise ConfigError("Config must contain list field 'routes'.")

    normalized: list[RouteConfig] = []
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ConfigError(f"routes[{idx}] must be object.")

        path = route.get("path")
        methods = route.get("methods", ["GET"])
        upstream_url = route.get("upstream_url")
        upstream_key = route.get("upstream_key")
        upstream_key_header = route.get("upstream_key_header", "Authorization")
        upstream_key_prefix = route.get("upstream_key_prefix", "Bearer ")

        if not isinstance(path, str) or not path.startswith("/"):
            raise ConfigError(f"routes[{idx}].path must be absolute path string.")
        if not isinstance(methods, list) or not methods or not all(isinstance(m, str) for m in methods):
            raise ConfigError(f"routes[{idx}].methods must be non-empty string list.")
        if not isinstance(upstream_url, str) or not upstream_url.startswith(("http://", "https://")):
            raise ConfigError(f"routes[{idx}].upstream_url must be absolute URL string.")
        if not isinstance(upstream_key, str) or not upstream_key.strip():
            raise ConfigError(f"routes[{idx}].upstream_key must be non-empty string.")
        if not isinstance(upstream_key_header, str) or not upstream_key_header.strip():
            raise ConfigError(f"routes[{idx}].upstream_key_header must be non-empty string.")
        if not isinstance(upstream_key_prefix, str):
            raise ConfigError(f"routes[{idx}].upstream_key_prefix must be string.")

        normalized.append(
            RouteConfig(
                path=path,
                path_regex=_compile_path_pattern(path),
                methods=[m.upper() for m in methods],
                upstream_url=upstream_url,
                upstream_key=upstream_key,
                upstream_key_header=upstream_key_header,
                upstream_key_prefix=upstream_key_prefix,
            )
        )
    return normalized


def _validate_proxy_secret(secret_header: str | None, authorization: str | None) -> None:
    proxy_secret_key = _get_proxy_secret_key()
    if not proxy_secret_key:
        raise HTTPException(status_code=500, detail="PROXY_SECRET_KEY is not set in environment")

    bearer_token = _extract_bearer_token(authorization)
    if secret_header == proxy_secret_key or bearer_token == proxy_secret_key:
        return

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing secret. Use X-Proxy-Secret or Authorization: Bearer <PROXY_SECRET_KEY>",
    )


def _build_proxy_headers(request_headers: Any, route: RouteConfig) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() not in {"host", "content-length", "x-proxy-secret"}
    }
    headers[route.upstream_key_header] = f"{route.upstream_key_prefix}{route.upstream_key}"
    return headers


def _build_route_auth_headers(route: RouteConfig) -> dict[str, str]:
    return {route.upstream_key_header: f"{route.upstream_key_prefix}{route.upstream_key}"}


def _should_stream_response(content_type: str, request: Request) -> bool:
    stream_flag = request.query_params.get("stream", "").lower()
    if stream_flag in {"1", "true", "yes"}:
        return True
    return "text/event-stream" in content_type or "application/x-ndjson" in content_type


async def _fetch_models_from_source(client: httpx.AsyncClient, source: RouteConfig) -> list[dict[str, Any]]:
    target_url = f"{_extract_base_url(source.upstream_url)}/v1/models"
    response = await client.get(target_url, headers=_build_route_auth_headers(source))
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected /v1/models response shape: root is not object")

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("Unexpected /v1/models response shape: data is not list")

    return data


async def _aggregate_models_from_all_routes(routes: list[RouteConfig], timeout: float | None) -> dict[str, Any]:
    unique_sources: dict[tuple[str, str, str, str], RouteConfig] = {}
    for route in routes:
        base = _extract_base_url(route.upstream_url)
        source_key = (base, route.upstream_key_header, route.upstream_key_prefix, route.upstream_key)
        unique_sources.setdefault(source_key, route)

    models_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for (base, _, _, _), source in unique_sources.items():
            try:
                models = await _fetch_models_from_source(client, source)
                for model in models:
                    if isinstance(model, dict):
                        model_id = model.get("id")
                        if isinstance(model_id, str) and model_id:
                            models_by_id.setdefault(model_id, model)
                        else:
                            synthetic_id = json.dumps(model, sort_keys=True, ensure_ascii=False)
                            models_by_id.setdefault(synthetic_id, model)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base}: {exc}")

    if not models_by_id and errors:
        raise HTTPException(
            status_code=502,
            detail={"message": "Failed to aggregate models from all routers", "errors": errors},
        )

    return {"object": "list", "data": list(models_by_id.values()), "errors": errors}


async def _aggregate_health_from_all_routes(routes: list[RouteConfig], timeout: float | None) -> dict[str, Any]:
    health_routes = [route for route in routes if route.path == "/health" and "GET" in route.methods]
    if not health_routes:
        raise HTTPException(status_code=404, detail="No /health routes configured")

    checks: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for route in health_routes:
            try:
                response = await client.get(route.upstream_url, headers=_build_route_auth_headers(route))
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    payload: Any = response.json()
                else:
                    payload = response.text

                checks.append(
                    {
                        "upstream": route.upstream_url,
                        "status_code": response.status_code,
                        "ok": response.is_success,
                        "payload": payload,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    {
                        "upstream": route.upstream_url,
                        "status_code": None,
                        "ok": False,
                        "error": str(exc),
                    }
                )

    overall_ok = all(item.get("ok", False) for item in checks)
    return {
        "object": "health.aggregate",
        "ok": overall_ok,
        "total": len(checks),
        "healthy": sum(1 for item in checks if item.get("ok", False)),
        "checks": checks,
    }


@app.get("/_health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_request(
    full_path: str,
    request: Request,
    x_proxy_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Response:
    _validate_proxy_secret(x_proxy_secret, authorization)
    incoming_path = "/" + full_path
    timeout = _get_request_timeout(request)

    try:
        routes = _load_routes_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if incoming_path == "/v1/models" and request.method.upper() == "GET":
        return JSONResponse(status_code=200, content=await _aggregate_models_from_all_routes(routes, timeout))

    if incoming_path == "/health" and request.method.upper() == "GET":
        health = await _aggregate_health_from_all_routes(routes, timeout)
        status_code = 200 if health["ok"] else 503
        return JSONResponse(status_code=status_code, content=health)

    resolved: tuple[RouteConfig, dict[str, str]] | None = None
    for candidate in routes:
        match = candidate.path_regex.match(incoming_path)
        if match and request.method.upper() in candidate.methods:
            resolved = (candidate, match.groupdict())
            break

    if resolved is None:
        raise HTTPException(status_code=404, detail="Route is not enabled by current config")

    route, path_params = resolved

    try:
        upstream_url = route.upstream_url.format(**path_params)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing upstream_url template var: {exc}") from exc

    body = await request.body()
    query_params = list(request.query_params.multi_items())
    headers = _build_proxy_headers(request.headers, route)

    client = httpx.AsyncClient(timeout=timeout)
    upstream_request = client.build_request(
        method=request.method,
        url=upstream_url,
        params=query_params,
        content=body,
        headers=headers,
    )
    upstream_response = await client.send(upstream_request, stream=True)

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }

    content_type = upstream_response.headers.get("content-type", "")

    if _should_stream_response(content_type, request):

        async def stream_body() -> Any:
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=content_type or None,
        )

    try:
        content = await upstream_response.aread()
    finally:
        await upstream_response.aclose()
        await client.aclose()

    if "application/json" in content_type:
        return JSONResponse(
            status_code=upstream_response.status_code,
            content=json.loads(content),
            headers=response_headers,
        )

    return Response(
        content=content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=content_type or None,
    )
